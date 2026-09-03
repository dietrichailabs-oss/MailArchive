from __future__ import annotations

from pathlib import Path

from mailarchive.database.readonly import connect_readonly
from mailarchive.archive.hashing import sha256_file
from mailarchive.archive.manifest import ManifestStore
from mailarchive.archive.verifier import Verifier, VerificationError


class ArchiveIntegrityVerifier:
    """Read-only archive consistency check. Never repairs or rewrites user archives."""

    def __init__(self, root):
        self.root = Path(root).resolve()

    def _safe_path(self, relative):
        if not relative:
            return None
        path = (self.root / relative).resolve()
        try:
            path.relative_to(self.root)
        except ValueError:
            return None
        return path

    def verify(self):
        issues = []
        db = connect_readonly(self.root)
        try:
            manifest = ManifestStore(self.root).load()
        except Exception as exc:
            manifest = {'messages': {}}
            issues.append({'type': 'MANIFEST_INVALID', 'detail': str(exc)})
        manifest_messages = manifest.get('messages') if isinstance(manifest, dict) else {}
        if not isinstance(manifest_messages, dict):
            manifest_messages = {}
            issues.append({'type': 'MANIFEST_MESSAGES_INVALID'})

        rows = db.execute("SELECT * FROM messages WHERE verification_status='VERIFIED'").fetchall()
        verified_ids = {row['archive_id'] for row in rows}
        for row in rows:
            aid = row['archive_id']
            path = self._safe_path(row['eml_path'])
            if path is None:
                issues.append({'archive_id': aid, 'type': 'EML_PATH_UNSAFE'})
                continue
            if not path.is_file():
                issues.append({'archive_id': aid, 'type': 'EML_MISSING'})
                continue
            try:
                actual = sha256_file(path)
            except OSError as exc:
                issues.append({'archive_id': aid, 'type': 'EML_UNREADABLE', 'detail': str(exc)})
                continue
            if actual != row['sha256']:
                issues.append({'archive_id': aid, 'type': 'DB_HASH_MISMATCH'})
            try:
                Verifier().verify_file(path, row['sha256'])
            except (VerificationError, OSError) as exc:
                issues.append({'archive_id': aid, 'type': 'MIME_VERIFICATION_FAILED', 'detail': str(exc)})

            mr = manifest_messages.get(aid)
            if not mr:
                issues.append({'archive_id': aid, 'type': 'MANIFEST_RECORD_MISSING'})
            else:
                if mr.get('sha256') != actual:
                    issues.append({'archive_id': aid, 'type': 'MANIFEST_HASH_MISMATCH'})
                if mr.get('eml_relative_path') != row['eml_path']:
                    issues.append({'archive_id': aid, 'type': 'MANIFEST_PATH_MISMATCH'})
                if int(mr.get('attachment_count') or 0) != int(row['attachment_count'] or 0):
                    issues.append({'archive_id': aid, 'type': 'MANIFEST_ATTACHMENT_COUNT_MISMATCH'})

            attachment_rows = db.execute(
                "SELECT * FROM attachments WHERE archive_id=? ORDER BY id", (aid,)
            ).fetchall()
            if len(attachment_rows) != int(row['attachment_count'] or 0):
                issues.append({'archive_id': aid, 'type': 'DB_ATTACHMENT_COUNT_MISMATCH'})
            for attachment in attachment_rows:
                apath = self._safe_path(attachment['relative_path'])
                if apath is None:
                    issues.append({'archive_id': aid, 'type': 'ATTACHMENT_PATH_UNSAFE', 'path': attachment['relative_path']})
                    continue
                if attachment['extraction_status'] != 'EXTRACTED':
                    issues.append({'archive_id': aid, 'type': 'ATTACHMENT_NOT_EXTRACTED', 'path': attachment['relative_path']})
                    continue
                if not apath.is_file():
                    issues.append({'archive_id': aid, 'type': 'ATTACHMENT_MISSING', 'path': attachment['relative_path']})
                    continue
                if sha256_file(apath) != attachment['sha256']:
                    issues.append({'archive_id': aid, 'type': 'ATTACHMENT_HASH_MISMATCH', 'path': attachment['relative_path']})

            hash_rows = db.execute(
                "SELECT object_kind,relative_path,sha256,size FROM hashes WHERE archive_id=?", (aid,)
            ).fetchall()
            mime_hash_rows = [h for h in hash_rows if h['object_kind'] == 'MIME']
            if len(mime_hash_rows) != 1:
                issues.append({'archive_id': aid, 'type': 'MIME_HASH_ACCOUNTING_MISMATCH'})
            elif mime_hash_rows[0]['relative_path'] != row['eml_path'] or mime_hash_rows[0]['sha256'] != row['sha256']:
                issues.append({'archive_id': aid, 'type': 'MIME_HASH_LEDGER_MISMATCH'})
            attachment_hash_rows = [h for h in hash_rows if h['object_kind'] == 'ATTACHMENT']
            if len(attachment_hash_rows) != len(attachment_rows):
                issues.append({'archive_id': aid, 'type': 'ATTACHMENT_HASH_LEDGER_COUNT_MISMATCH'})

            fts = db.execute("SELECT archive_id FROM message_fts WHERE archive_id=?", (aid,)).fetchone()
            if not fts:
                issues.append({'archive_id': aid, 'type': 'SEARCH_INDEX_RECORD_MISSING'})

        for aid in manifest_messages:
            if aid not in verified_ids:
                issues.append({'archive_id': aid, 'type': 'MANIFEST_RECORD_WITHOUT_VERIFIED_DB_ROW'})

        # Extracted files not represented by DB rows are reported; verification never deletes them.
        tracked = {
            (self.root / row['relative_path']).resolve()
            for row in db.execute("SELECT relative_path FROM attachments WHERE relative_path IS NOT NULL").fetchall()
            if self._safe_path(row['relative_path']) is not None
        }
        attachments_root = self.root / 'attachments'
        if attachments_root.exists():
            for path in attachments_root.rglob('*'):
                if path.is_file() and path.resolve() not in tracked and not path.name.endswith('.tmp'):
                    issues.append({'type': 'UNTRACKED_ATTACHMENT_FILE', 'path': path.relative_to(self.root).as_posix()})

        db.close()
        return {
            'status': 'HEALTHY' if not issues else 'DAMAGED',
            'issues': issues,
            'verified_messages': len(rows),
        }
