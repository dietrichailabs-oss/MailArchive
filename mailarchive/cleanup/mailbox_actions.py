from mailarchive.cleanup.eligibility import CleanupEligibilityService, CleanupNotEligible, CleanupOutcomeUncertain
from mailarchive.database.connection import connect
from mailarchive.providers.contracts import MessageNotFound
from datetime import datetime, timezone
import uuid


class CleanupService:
    def __init__(self, provider, root):
        self.provider = provider
        self.root = root
        self.eligibility = CleanupEligibilityService(root)

    def _record(self, archive_id: str, status: str, detail: str) -> None:
        db = connect(self.root)
        with db:
            db.execute(
                'UPDATE cleanup_state SET status=?,last_detail=? WHERE archive_id=?',
                (status, detail, archive_id),
            )
        db.close()

    @staticmethod
    def _normalized_recipients(value) -> tuple[str, ...]:
        if isinstance(value, str):
            values = value.split(',')
        else:
            values = value or []
        return tuple(sorted(x.strip().casefold() for x in values if x and x.strip()))

    def _identity_matches(self, archived: dict, current) -> bool:
        # Provider IDs are requested as Graph ImmutableIds in production, but cleanup still
        # does a metadata snapshot comparison so an ID alone can never authorize mutation.
        if current.ref.provider_id != archived['provider_id']:
            return False
        archived_imid = archived.get('internet_message_id') or ''
        if archived_imid and current.ref.internet_message_id != archived_imid:
            return False
        comparisons = (
            ((archived.get('subject') or ''), (current.subject or '')),
            ((archived.get('sender') or '').casefold(), (current.sender or '').casefold()),
            ((archived.get('received_ts') or ''), (current.received_ts or '')),
            ((archived.get('sent_ts') or ''), (current.sent_ts or '')),
        )
        if any(left != right for left, right in comparisons):
            return False
        if self._normalized_recipients(archived.get('recipients')) != self._normalized_recipients(current.recipients):
            return False
        return True

    def move_verified(self, archive_ids):
        # De-duplicate caller input so one archive record can authorize at most one mailbox mutation attempt.
        archive_ids = list(dict.fromkeys(archive_ids))
        cleanup_job_id = str(uuid.uuid4())
        self.last_job_id = cleanup_job_id
        started = datetime.now(timezone.utc).isoformat()
        db = connect(self.root)
        with db:
            db.execute(
                '''INSERT INTO cleanup_jobs(cleanup_job_id,status,requested_count,started_at)
                   VALUES(?,?,?,?)''',
                (cleanup_job_id, 'RUNNING', len(archive_ids), started),
            )
        db.close()

        out = []
        for aid in archive_ids:
            # All eligibility and metadata checks happen before the durable MOVING marker.
            # Once MOVING is recorded, any exception is treated as an uncertain remote
            # outcome and the message is never automatically retried.
            try:
                pid = self.eligibility.resolve_provider_id(aid)
                archived = self._archived_identity(aid)
                current = self.provider.get_message_metadata(pid)
            except CleanupOutcomeUncertain:
                out.append((aid, 'UNKNOWN_MOVE_OUTCOME'))
                continue
            except CleanupNotEligible:
                # Do not rewrite cleanup_state here. In particular, a caller must never
                # be able to turn MOVED back into SKIPPED by resubmitting an archive ID.
                out.append((aid, 'SKIPPED_NOT_VERIFIED'))
                continue
            except MessageNotFound as exc:
                self._record(aid, 'MISSING', str(exc))
                out.append((aid, 'MISSING'))
                continue
            except Exception as exc:
                self._record(aid, 'FAILED', str(exc))
                out.append((aid, 'FAILED'))
                continue

            if not self._identity_matches(archived, current):
                self._record(aid, 'SKIPPED', 'provider identity/metadata no longer matches archived snapshot')
                out.append((aid, 'SKIPPED_IDENTITY_MISMATCH'))
                continue

            try:
                # This local commit is intentionally before the Graph mutation. A crash
                # after this point leaves MOVING, which cleanup eligibility treats as
                # reconciliation-required rather than retryable.
                self._record(aid, 'MOVING', 'mailbox move requested; outcome not yet confirmed locally')
            except Exception as exc:
                # No provider mutation has been attempted yet, so this is a normal local
                # failure and is safe to retry after the archive becomes writable again.
                try:
                    self._record(aid, 'FAILED', f'could not persist pre-move state: {exc}')
                except Exception:
                    pass
                out.append((aid, 'FAILED'))
                continue

            try:
                new_id = self.provider.move_message_to_deleted_items(pid)
            except Exception as exc:
                # The provider may have accepted the move even if the response was lost.
                # Never claim failure or retry automatically when remote outcome is unknown.
                try:
                    self._record(aid, 'UNKNOWN_MOVE_OUTCOME', f'move outcome uncertain: {exc}')
                except Exception:
                    # MOVING is itself a fail-closed state if the follow-up DB write fails.
                    pass
                out.append((aid, 'UNKNOWN_MOVE_OUTCOME'))
                continue

            try:
                self._record(aid, 'MOVED', f'moved to Deleted Items provider_id={new_id}')
            except Exception:
                # Graph returned success but local confirmation could not be committed.
                # Leave MOVING in place and require reconciliation instead of retrying.
                out.append((aid, 'UNKNOWN_MOVE_OUTCOME'))
                continue
            out.append((aid, 'MOVED'))

        moved = sum(status == 'MOVED' for _, status in out)
        missing = sum(status == 'MISSING' for _, status in out)
        failed = sum(status == 'FAILED' for _, status in out)
        unknown = sum(status == 'UNKNOWN_MOVE_OUTCOME' for _, status in out)
        skipped = len(out) - moved - missing - failed - unknown
        if unknown:
            final = 'RECONCILIATION_REQUIRED'
        else:
            final = 'NO_CHANGES' if not out else ('COMPLETED' if moved == len(out) else ('PARTIAL' if moved else 'NO_CHANGES'))
        db = connect(self.root)
        with db:
            db.execute(
                '''UPDATE cleanup_jobs SET status=?,moved_count=?,failed_count=?,skipped_count=?,missing_count=?,unknown_count=?,stopped_at=?
                   WHERE cleanup_job_id=?''',
                (final, moved, failed, skipped, missing, unknown, datetime.now(timezone.utc).isoformat(), cleanup_job_id),
            )
        db.close()
        return out

    def _archived_identity(self, archive_id: str) -> dict:
        db = connect(self.root)
        row = db.execute(
            '''SELECT provider_id,internet_message_id,subject,sender,recipients,received_ts,sent_ts
               FROM messages WHERE archive_id=?''',
            (archive_id,),
        ).fetchone()
        db.close()
        if not row:
            return {
                'provider_id': '', 'internet_message_id': None, 'subject': '', 'sender': '',
                'recipients': '', 'received_ts': '', 'sent_ts': '',
            }
        return dict(row)
