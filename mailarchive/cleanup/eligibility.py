from pathlib import Path
import json

from mailarchive.archive.hashing import sha256_file
from mailarchive.archive.verifier import Verifier, VerificationError
from mailarchive.archive.manifest import ManifestStore
from mailarchive.database.readonly import connect_readonly


class CleanupNotEligible(RuntimeError):
    pass


class CleanupOutcomeUncertain(CleanupNotEligible):
    pass


class CleanupEligibilityService:
    def __init__(self, root):
        self.root = Path(root)

    def _manifest_record(self, archive_id: str) -> dict:
        try:
            manifest = ManifestStore(self.root).load()
            row = manifest['messages'][archive_id]
            if not row.get('sha256'):
                raise KeyError('sha256')
            return row
        except Exception as exc:
            raise CleanupNotEligible('manifest record missing or invalid') from exc

    def _verify_attachments(self, archive_id: str, expected_count: int) -> None:
        db = connect_readonly(self.root)
        try:
            rows = db.execute(
                "SELECT relative_path,sha256,extraction_status FROM attachments WHERE archive_id=?",
                (archive_id,),
            ).fetchall()
        finally:
            db.close()
        if len(rows) != int(expected_count or 0):
            raise CleanupNotEligible('attachment accounting changed after verification')
        for row in rows:
            if row['extraction_status'] != 'EXTRACTED' or not row['relative_path'] or not row['sha256']:
                raise CleanupNotEligible('attachment extraction is incomplete')
            path = self.root / row['relative_path']
            try:
                if not path.is_file() or sha256_file(path) != row['sha256']:
                    raise CleanupNotEligible('attachment integrity check failed')
            except OSError as exc:
                raise CleanupNotEligible('attachment integrity check failed') from exc

    @staticmethod
    def _assert_archive_cleanup_allowed(db) -> None:
        # Cleanup is a post-archive action. The backend must enforce the same global
        # job-completion boundary as the UI so no future caller can expose VERIFIED
        # items from a cancelled/interrupted/incomplete latest archive job.
        row = db.execute(
            """SELECT job_id,status,stop_reason FROM archive_jobs
               ORDER BY updated_at DESC, created_at DESC LIMIT 1"""
        ).fetchone()
        if not row:
            raise CleanupNotEligible('cleanup requires a completed archive job')
        if row['status'] != 'COMPLETED':
            detail = f"status={row['status']}"
            if row['stop_reason']:
                detail += f", stop_reason={row['stop_reason']}"
            raise CleanupNotEligible(
                f"archive cleanup is blocked by incomplete latest job {row['job_id']}: {detail}"
            )

    def archive_cleanup_block_reason(self) -> str | None:
        try:
            db = connect_readonly(self.root)
        except (FileNotFoundError, OSError):
            return 'archive database is unavailable'
        try:
            self._assert_archive_cleanup_allowed(db)
        except CleanupNotEligible as exc:
            return str(exc)
        finally:
            db.close()
        return None

    def resolve_provider_id(self, archive_id):
        try:
            db = connect_readonly(self.root)
        except (FileNotFoundError, OSError) as exc:
            raise CleanupNotEligible('archive database is unavailable') from exc
        try:
            self._assert_archive_cleanup_allowed(db)
            row = db.execute(
                '''SELECT m.verification_status,m.identity_ambiguous,m.eml_path,m.sha256,m.attachment_count,
                          m.internet_message_id,c.provider_id_at_archive,c.status
                   FROM messages m JOIN cleanup_state c USING(archive_id)
                   WHERE m.archive_id=?''',
                (archive_id,),
            ).fetchone()
        finally:
            # Always release the read handle before propagating a safety rejection.
            # This matters on Windows, where an outstanding SQLite handle can prevent
            # archive.db rename/move operations even though cleanup itself failed closed.
            db.close()
        if not row or row['verification_status'] != 'VERIFIED':
            raise CleanupNotEligible('message is not VERIFIED')
        if row['identity_ambiguous']:
            raise CleanupNotEligible('message identity is ambiguous')
        if row['status'] == 'MOVED':
            raise CleanupNotEligible('message was already moved')
        if row['status'] in {'MOVING', 'UNKNOWN_MOVE_OUTCOME'}:
            raise CleanupOutcomeUncertain('a previous move attempt has an uncertain outcome and requires reconciliation')
        if not row['eml_path'] or not row['sha256']:
            raise CleanupNotEligible('verified message lacks local integrity metadata')
        manifest = self._manifest_record(archive_id)
        if manifest.get('sha256') != row['sha256']:
            raise CleanupNotEligible('manifest/database hash disagreement')
        if int(manifest.get('attachment_count') or 0) != int(row['attachment_count'] or 0):
            raise CleanupNotEligible('manifest/database attachment count disagreement')
        try:
            Verifier().verify_file(self.root / row['eml_path'], row['sha256'])
        except (VerificationError, OSError) as exc:
            raise CleanupNotEligible(f'local archive integrity check failed: {exc}') from exc
        self._verify_attachments(archive_id, row['attachment_count'])
        return row['provider_id_at_archive']

    def eligible_archive_ids(self):
        db = connect_readonly(self.root)
        try:
            try:
                self._assert_archive_cleanup_allowed(db)
            except CleanupNotEligible:
                return []
            rows = db.execute(
                '''SELECT m.archive_id FROM messages m JOIN cleanup_state c USING(archive_id)
                   WHERE m.verification_status='VERIFIED'
                     AND m.identity_ambiguous=0
                     AND c.status NOT IN ('MOVED','MOVING','UNKNOWN_MOVE_OUTCOME') '''
            ).fetchall()
        finally:
            db.close()
        eligible = []
        for row in rows:
            try:
                self.resolve_provider_id(row['archive_id'])
            except CleanupNotEligible:
                continue
            eligible.append(row['archive_id'])
        return eligible
