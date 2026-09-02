from email import policy
from email.parser import BytesParser
from pathlib import Path
from datetime import datetime, timezone
import errno
import hashlib
import json
import sqlite3
import time
import uuid

from mailarchive.archive.hashing import sha256_bytes
from mailarchive.archive.mime_store import MimeStore
from mailarchive.archive.manifest import ManifestStore
from mailarchive.archive.verifier import Verifier
from mailarchive.archive.checkpointing import CheckpointStore
from mailarchive.archive.deduplication import IdentityGuard
from mailarchive.database.connection import connect
from mailarchive.attachments.store import AttachmentStore
from mailarchive.archive.mime_index import extract_searchable_body
from mailarchive.providers.contracts import RateLimited, NetworkUnavailable, AuthenticationRequired, OperationCancelled
from mailarchive.reporting.archive_report import write_archive_report


def _is_fatal_storage_error(exc: Exception) -> bool:
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OSError) and current.errno in {errno.ENOSPC, errno.EROFS, errno.EACCES, errno.EIO}:
            return True
        if isinstance(current, sqlite3.OperationalError):
            text = str(current).casefold()
            if any(marker in text for marker in ('disk is full', 'database or disk is full', 'readonly', 'read-only', 'i/o error')):
                return True
        current = current.__cause__ or current.__context__
    return False


class ArchiveIdentityMismatch(RuntimeError):
    """The requested job does not belong in the existing portable archive root."""


def _account_key(metadata: dict | None) -> str:
    metadata = metadata if isinstance(metadata, dict) else {}
    value = metadata.get('account_id') or metadata.get('principal_hint') or ''
    return str(value).strip().casefold()


class ArchiveJobEngine:
    MAX_RATE_LIMIT_RETRIES = 4
    DISCOVERY_CHECKPOINT_INTERVAL = 100

    def __init__(self, provider, root, *, sleep=time.sleep, progress=None):
        self.provider = provider
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.mime_store = MimeStore(root)
        self.manifest = ManifestStore(root)
        self.verifier = Verifier()
        self.attachments = AttachmentStore(root)
        self.checkpoints = CheckpointStore(root)
        self.identity_guard = IdentityGuard(root)
        self.cancelled = False
        self.sleep = sleep
        self.progress = progress

    def cancel(self):
        self.cancelled = True

    def _emit(self, event: str, **payload):
        if self.progress is not None:
            try:
                self.progress({'event': event, **payload})
            except Exception:
                # A presentation-layer callback can never alter archive safety/state.
                pass

    def _archive_id(self, message):
        # Never key solely on Internet Message ID: duplicates are legal in hostile/malformed mailboxes.
        stable = f'v2|{message.ref.provider_id}|{message.ref.folder_id}|{message.ref.internet_message_id or ""}'
        return hashlib.sha256(stable.encode('utf-8', 'surrogatepass')).hexdigest()[:24]


    def _provider_account_metadata(self) -> dict:
        try:
            return dict(self.provider.get_account_metadata() or {})
        except Exception:
            return {}

    def _assert_archive_identity(self, db, start: str | None, end: str | None, account: dict) -> None:
        requested_range = (start or None, end or None)
        existing_ranges = {
            (row['start_date'] or None, row['end_date'] or None)
            for row in db.execute('SELECT DISTINCT start_date,end_date FROM archive_jobs')
        }
        if existing_ranges and existing_ranges != {requested_range}:
            raise ArchiveIdentityMismatch(
                f'archive root belongs to date range(s) {sorted(existing_ranges, key=str)!r}, not {requested_range!r}'
            )

        current_account = _account_key(account)
        row = db.execute("SELECT value FROM archive_metadata WHERE key='source_account'").fetchone()
        if row:
            try:
                stored_account = _account_key(json.loads(row['value']))
            except Exception as exc:
                raise ArchiveIdentityMismatch('archive source-account provenance is unreadable') from exc
            if current_account and not stored_account:
                raise ArchiveIdentityMismatch('archive source-account provenance is missing')
            if current_account and stored_account != current_account:
                raise ArchiveIdentityMismatch('archive root belongs to a different mailbox account')
        elif existing_ranges and current_account:
            raise ArchiveIdentityMismatch('existing archive has no source-account provenance')

    def _record_archive_context(self, db, folder_ids, account: dict | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        created_at = now
        if not db.execute("SELECT 1 FROM archive_metadata WHERE key='archive_created_at'").fetchone():
            # dev/legacy archives may predate the dedicated DB key. Preserve their original
            # creation time from portable metadata instead of making a repeated run look new.
            for candidate in (self.root / 'archive_info.json', self.root / 'manifest.json'):
                try:
                    doc = json.loads(candidate.read_text(encoding='utf-8'))
                    value = doc.get('archive_creation_timestamp') if isinstance(doc, dict) else None
                    if isinstance(value, str) and value.strip():
                        created_at = value.strip()
                        break
                except Exception:
                    pass
        account = dict(account if account is not None else self._provider_account_metadata())
        account_id = str(account.get('account_id') or account.get('principal_hint') or 'unknown')
        principal_hint = str(account.get('principal_hint') or '')
        display_name = str(account.get('display_name') or principal_hint or account_id)
        with db:
            db.execute(
                '''INSERT INTO accounts(account_id,display_name,principal_hint,created_at,last_used_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(account_id) DO UPDATE SET display_name=excluded.display_name,principal_hint=excluded.principal_hint,last_used_at=excluded.last_used_at''',
                (account_id, display_name, principal_hint, now, now),
            )
            db.execute(
                "INSERT OR IGNORE INTO archive_metadata(key,value) VALUES('archive_created_at',?)",
                (created_at,),
            )
            db.execute(
                "INSERT OR REPLACE INTO archive_metadata(key,value) VALUES('source_account',?)",
                (json.dumps({'account_id': account_id, 'display_name': display_name, 'principal_hint': principal_hint}, ensure_ascii=False),),
            )
        try:
            folder_rows = self.provider.list_folders()
        except Exception:
            folder_rows = []
        by_id = {str(row.get('id')): row for row in folder_rows if isinstance(row, dict) and row.get('id')}
        with db:
            for folder_id in folder_ids:
                row = by_id.get(str(folder_id), {})
                name = str(row.get('name') or folder_id)
                parent = row.get('parent_id')
                db.execute(
                    '''INSERT INTO folders(folder_id,display_name,parent_folder_id,source_account_id,last_seen_at)
                       VALUES(?,?,?,?,?)
                       ON CONFLICT(folder_id) DO UPDATE SET display_name=excluded.display_name,parent_folder_id=excluded.parent_folder_id,source_account_id=excluded.source_account_id,last_seen_at=excluded.last_seen_at''',
                    (str(folder_id), name, parent, account_id, now),
                )

    def _compact_current_manifest(self, db, job_id: str) -> None:
        job = db.execute('SELECT status,selected_folders,start_date,end_date FROM archive_jobs WHERE job_id=?', (job_id,)).fetchone()
        if not job:
            return
        counts = db.execute(
            "SELECT COUNT(*) total, SUM(CASE WHEN verification_status='VERIFIED' THEN 1 ELSE 0 END) verified, SUM(CASE WHEN verification_status='FAILED' THEN 1 ELSE 0 END) failed, COALESCE(SUM(CASE WHEN verification_status='VERIFIED' THEN mime_size ELSE 0 END),0) archive_size FROM messages"
        ).fetchone()
        metadata_rows = {row['key']: row['value'] for row in db.execute('SELECT key,value FROM archive_metadata')}
        try:
            source_account = json.loads(metadata_rows.get('source_account', '{}'))
        except Exception:
            source_account = {}

        selected_folder_ids: set[str] = set()
        for row in db.execute('SELECT selected_folders FROM archive_jobs'):
            try:
                values = json.loads(row['selected_folders'])
            except Exception:
                values = []
            if isinstance(values, list):
                selected_folder_ids.update(str(value) for value in values)
        selected_folders = sorted(selected_folder_ids)
        folder_details = []
        if selected_folders:
            placeholders = ','.join('?' for _ in selected_folders)
            rows = db.execute(
                f'SELECT folder_id,display_name,parent_folder_id FROM folders WHERE folder_id IN ({placeholders}) ORDER BY display_name,folder_id',
                tuple(selected_folders),
            ).fetchall()
            by_id = {
                str(row['folder_id']): {
                    'id': str(row['folder_id']),
                    'name': str(row['display_name'] or row['folder_id']),
                    'parent_id': row['parent_folder_id'],
                }
                for row in rows
            }
            folder_details = [by_id.get(folder_id, {'id': folder_id, 'name': folder_id, 'parent_id': None}) for folder_id in selected_folders]

        created_at = metadata_rows.get('archive_created_at') or datetime.now(timezone.utc).isoformat()
        self.manifest.update_archive_metadata({
            'application_version': __import__('mailarchive').__version__,
            'archive_creation_timestamp': created_at,
            'archive_last_updated_timestamp': datetime.now(timezone.utc).isoformat(),
            'selected_date_range': {'start': job['start_date'], 'end': job['end_date'], 'inclusive': True},
            'selected_folders': selected_folders,
            'selected_folder_details': folder_details,
            'source_account': source_account,
            'message_count': int(counts['total'] or 0),
            'verified_count': int(counts['verified'] or 0),
            'failed_count': int(counts['failed'] or 0),
            'archive_size': int(counts['archive_size'] or 0),
            'last_job_status': job['status'],
        })

    def _download_with_retry(self, provider_id: str) -> bytes:
        attempt = 0
        while True:
            try:
                return self.provider.get_message_mime(provider_id)
            except RateLimited as exc:
                attempt += 1
                if attempt > self.MAX_RATE_LIMIT_RETRIES:
                    raise
                if self.cancelled:
                    raise OperationCancelled('archive cancellation requested during provider backoff') from exc
                self.sleep(exc.retry_after)

    def run(self, folder_ids, start=None, end=None, *, job_id: str | None = None):
        job_id = job_id or str(uuid.uuid4())
        db = connect(self.root)
        account = self._provider_account_metadata()
        try:
            self._assert_archive_identity(db, start, end, account)
            self.checkpoints.begin_or_resume(job_id, list(folder_ids), start, end)
            self._record_archive_context(db, list(folder_ids), account)
        except Exception:
            db.close()
            raise
        results = []
        discovered = 0
        any_failed = False
        try:
            for message in self.provider.discover_messages(folder_ids, start, end):
                discovered += 1
                if discovered % self.DISCOVERY_CHECKPOINT_INTERVAL == 0:
                    # Discovery count is resumable progress metadata, not verification evidence.
                    # Batch its durable update; exact count is forced in finally below.
                    self.checkpoints.set_discovered(job_id, discovered, db=db)
                self._emit('discovered', job_id=job_id, discovered=discovered, folder=message.ref.folder_id, provider_id=message.ref.provider_id)
                aid = self._archive_id(message)
                if self.cancelled:
                    self.checkpoints.finish(job_id, 'CANCELLED', db=db)
                    results.append((aid, 'CANCELLED'))
                    break

                prior_job_status = self.checkpoints.item_status(job_id, aid, db=db)
                row = db.execute(
                    'SELECT verification_status FROM messages WHERE archive_id=?', (aid,)
                ).fetchone()
                if row and row['verification_status'] == 'VERIFIED':
                    status = 'SKIPPED_VERIFIED'
                    self.checkpoints.record_item(job_id, aid, message.ref.provider_id, status, db=db)
                    results.append((aid, status))
                    self._emit('skipped', job_id=job_id, archive_id=aid, provider_id=message.ref.provider_id)
                    continue
                if prior_job_status in {'VERIFIED', 'SKIPPED_VERIFIED'}:
                    status = 'SKIPPED_VERIFIED'
                    results.append((aid, status))
                    self._emit('skipped', job_id=job_id, archive_id=aid, provider_id=message.ref.provider_id)
                    continue

                try:
                    self._emit('downloading', job_id=job_id, archive_id=aid, provider_id=message.ref.provider_id)
                    raw = self._download_with_retry(message.ref.provider_id)
                    self._emit('downloaded', job_id=job_id, archive_id=aid, provider_id=message.ref.provider_id, bytes_received=len(raw))
                    expected = sha256_bytes(raw)
                    path = self.mime_store.write_atomic(aid, raw)
                    self._emit('written', job_id=job_id, archive_id=aid, provider_id=message.ref.provider_id, bytes_written=len(raw))
                    verification = self.verifier.verify_file(path, expected)
                    parsed = BytesParser(policy=policy.default).parsebytes(raw)
                    recipients = ', '.join(message.recipients)
                    body = extract_searchable_body(parsed)
                    attachments = self.attachments.extract(aid, parsed)
                    record = {
                        'archive_id': aid,
                        'provider_id': message.ref.provider_id,
                        'internet_message_id': message.ref.internet_message_id,
                        'folder': message.ref.folder_id,
                        'subject': message.subject,
                        'sender': message.sender,
                        'recipients': message.recipients,
                        'received_timestamp': message.received_ts,
                        'sent_timestamp': message.sent_ts,
                        'retrieval_timestamp': datetime.now(timezone.utc).isoformat(),
                        'mime_size': len(raw),
                        'eml_relative_path': str(path.relative_to(self.root)).replace('\\', '/'),
                        'sha256': expected,
                        'attachment_count': len(attachments),
                        'verification_status': 'VERIFIED',
                    }
                    with db:
                        db.execute(
                            '''INSERT OR REPLACE INTO messages(
                                 archive_id,provider_id,folder_id,internet_message_id,subject,sender,recipients,
                                 received_ts,sent_ts,retrieval_ts,eml_path,sha256,mime_size,attachment_count,
                                 verification_status,identity_ambiguous)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,COALESCE((SELECT identity_ambiguous FROM messages WHERE archive_id=?),0))''',
                            (
                                aid, message.ref.provider_id, message.ref.folder_id, message.ref.internet_message_id,
                                message.subject, message.sender, recipients, message.received_ts, message.sent_ts,
                                record['retrieval_timestamp'], record['eml_relative_path'], expected, len(raw),
                                len(attachments), 'PENDING', aid,
                            ),
                        )
                        db.execute(
                            '''INSERT OR REPLACE INTO cleanup_state(archive_id,provider_id_at_archive,status,last_detail)
                               VALUES(?,?,COALESCE((SELECT status FROM cleanup_state WHERE archive_id=?),'NOT_ATTEMPTED'),'')''',
                            (aid, message.ref.provider_id, aid),
                        )
                        db.execute('DELETE FROM attachments WHERE archive_id=?', (aid,))
                        for attachment in attachments:
                            db.execute(
                                '''INSERT INTO attachments(
                                     archive_id,filename,sanitized_filename,mime_type,size,sha256,relative_path,extraction_status,content_id)
                                   VALUES(?,?,?,?,?,?,?,?,?)''',
                                (
                                    aid, attachment['filename'], attachment['sanitized_filename'], attachment['mime_type'],
                                    attachment['size'], attachment['sha256'], attachment['relative_path'],
                                    attachment['extraction_status'], attachment.get('content_id'),
                                ),
                            )
                        db.execute('DELETE FROM recipients WHERE archive_id=?', (aid,))
                        for recipient in message.recipients:
                            if recipient:
                                db.execute(
                                    'INSERT INTO recipients(archive_id,kind,address) VALUES(?,?,?)',
                                    (aid, 'TO', recipient),
                                )
                        db.execute('DELETE FROM hashes WHERE archive_id=?', (aid,))
                        db.execute(
                            'INSERT INTO hashes(archive_id,object_kind,relative_path,sha256,size) VALUES(?,?,?,?,?)',
                            (aid, 'MIME', record['eml_relative_path'], expected, len(raw)),
                        )
                        for attachment in attachments:
                            db.execute(
                                'INSERT INTO hashes(archive_id,object_kind,relative_path,sha256,size) VALUES(?,?,?,?,?)',
                                (aid, 'ATTACHMENT', attachment['relative_path'], attachment['sha256'], attachment['size']),
                            )
                        # Identity ambiguity, manifest durability, VERIFIED promotion, search
                        # indexing, and checkpoint accounting are one safety transaction. The
                        # manifest append fsyncs before the DB can commit VERIFIED. If anything
                        # below fails, SQLite rolls back and cleanup remains fail-closed.
                        self.identity_guard.register_and_check(
                            aid, message.ref.provider_id, message.ref.internet_message_id, db=db
                        )
                        self.manifest.upsert_verified(aid, record)
                        db.execute("UPDATE messages SET verification_status='VERIFIED' WHERE archive_id=?", (aid,))
                        db.execute(
                            'INSERT OR REPLACE INTO verification(archive_id,verified_at,detail) VALUES(?,?,?)',
                            (aid, verification['verified_at'], 'file+hash+mime+db+manifest verified'),
                        )
                        db.execute('DELETE FROM message_fts WHERE archive_id=?', (aid,))
                        db.execute(
                            '''INSERT INTO message_fts(archive_id,subject,sender,recipients,body,attachment_filenames)
                               VALUES(?,?,?,?,?,?)''',
                            (
                                aid, message.subject, message.sender, recipients, body,
                                ' '.join(a['sanitized_filename'] for a in attachments),
                            ),
                        )
                        status = 'VERIFIED'
                        self.checkpoints.record_item(job_id, aid, message.ref.provider_id, status, db=db)
                    results.append((aid, status))
                    self._emit('verified', job_id=job_id, archive_id=aid, provider_id=message.ref.provider_id, bytes_written=len(raw))
                except OperationCancelled as exc:
                    self.checkpoints.record_item(job_id, aid, message.ref.provider_id, 'CANCELLED', str(exc), db=db)
                    self.checkpoints.finish(job_id, 'CANCELLED', stop_reason='user_cancelled', db=db)
                    results.append((aid, 'CANCELLED'))
                    self._emit('stopped', job_id=job_id, reason='user_cancelled')
                    break
                except (NetworkUnavailable, AuthenticationRequired, RateLimited) as exc:
                    # Provider-wide transient/auth failures are resumable job interruptions, not
                    # permanent per-message archive failures. No mailbox mutation occurs.
                    self.checkpoints.record_item(job_id, aid, message.ref.provider_id, 'INTERRUPTED', str(exc), db=db)
                    self.checkpoints.finish(job_id, 'INTERRUPTED', stop_reason=type(exc).__name__, db=db)
                    results.append((aid, 'INTERRUPTED'))
                    self._emit('stopped', job_id=job_id, reason=type(exc).__name__)
                    break
                except Exception as exc:
                    any_failed = True
                    try:
                        with db:
                            db.execute(
                                '''INSERT OR IGNORE INTO messages(
                                     archive_id,provider_id,folder_id,internet_message_id,subject,sender,received_ts,
                                     verification_status)
                                   VALUES(?,?,?,?,?,?,?,?)''',
                                (
                                    aid, message.ref.provider_id, message.ref.folder_id,
                                    message.ref.internet_message_id, message.subject, message.sender,
                                    message.received_ts, 'FAILED',
                                ),
                            )
                            db.execute("UPDATE messages SET verification_status='FAILED' WHERE archive_id=?", (aid,))
                            db.execute(
                                'INSERT INTO errors(job_id,archive_id,code,detail,created_at) VALUES(?,?,?,?,?)',
                                (job_id, aid, type(exc).__name__, str(exc), datetime.now(timezone.utc).isoformat()),
                            )
                    except Exception:
                        pass
                    try:
                        self.checkpoints.record_item(job_id, aid, message.ref.provider_id, 'FAILED', str(exc), db=db)
                    except Exception:
                        pass
                    results.append((aid, 'FAILED'))
                    self._emit('failed', job_id=job_id, archive_id=aid, provider_id=message.ref.provider_id, error_type=type(exc).__name__)
                    if _is_fatal_storage_error(exc):
                        try:
                            self.checkpoints.finish(job_id, 'PARTIAL', stop_reason='storage_failure', db=db)
                        except Exception:
                            pass
                        self._emit('stopped', job_id=job_id, reason='storage_failure')
                        break
            else:
                final_status = 'PARTIAL' if any_failed else 'COMPLETED'
                self.checkpoints.finish(job_id, final_status, db=db)
                self._compact_current_manifest(db, job_id)
                self._emit('completed', job_id=job_id, status=final_status, discovered=discovered)
        finally:
            # Discovery is progress metadata, so it is batched during the run. Force the exact
            # count at every graceful/exception boundary when storage remains writable.
            try:
                self.checkpoints.set_discovered(job_id, discovered, db=db)
            except Exception:
                pass
            # Every terminated run gets a durable job state/report when storage remains writable.
            # A discovery/network exception leaves the job resumable as INTERRUPTED.
            try:
                row = db.execute('SELECT status FROM archive_jobs WHERE job_id=?', (job_id,)).fetchone()
                if row and row['status'] == 'RUNNING':
                    self.checkpoints.finish(job_id, 'INTERRUPTED', db=db)
            except Exception:
                pass
            try:
                self._compact_current_manifest(db, job_id)
            except Exception:
                pass
            try:
                write_archive_report(self.root, job_id)
            except Exception:
                pass
            db.close()
        return results
