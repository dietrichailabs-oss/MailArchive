from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import uuid

from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.archive.manager import ArchiveRegistry
from mailarchive.archive.planning import ArchivePlanner, ArchivePreview, require_destination_writable
from mailarchive.archive.runtime_assets import provision_portable_viewer
from mailarchive.cleanup.mailbox_actions import CleanupService
from mailarchive.cleanup.preview import CleanupPlan, CleanupPlanner
from mailarchive.integrity.verify_archive import ArchiveIntegrityVerifier
from mailarchive.database.connection import connect
from mailarchive.reporting.cleanup_report import write_cleanup_report
from mailarchive.viewer.launcher import launch_archive


@dataclass(frozen=True)
class ArchiveSelection:
    folder_ids: tuple[str, ...]
    start: str | None
    end: str | None
    destination: Path


@dataclass(frozen=True)
class ArchiveRunResult:
    job_id: str
    archive_root: Path
    items: tuple[tuple[str, str], ...]
    discovered: int
    processed: int
    verified: int
    skipped: int
    failed: int
    archive_size_bytes: int
    cancelled: bool
    status: str
    stop_reason: str = ''
    interrupted: bool = False
    portable_viewer_ready: bool = False

    @property
    def completed(self) -> bool:
        return self.status == 'COMPLETED'

    @property
    def resumable(self) -> bool:
        return self.status in {'PARTIAL', 'CANCELLED', 'INTERRUPTED'}


class MailArchiveController:
    """Headless application workflow. UI may orchestrate it but cannot bypass safety services."""

    def __init__(self, provider, *, registry: ArchiveRegistry | None = None, portable_viewer_source=None):
        self.provider = provider
        self.registry = registry
        self.portable_viewer_source = portable_viewer_source
        self.active_engine: ArchiveJobEngine | None = None

    def list_folders(self):
        return self.provider.list_folders()

    def preview(self, selection: ArchiveSelection) -> ArchivePreview:
        if not selection.folder_ids:
            raise ValueError('select at least one mailbox folder')
        if selection.start and selection.end and selection.start[:10] > selection.end[:10]:
            raise ValueError('start date cannot be after end date')
        return ArchivePlanner(self.provider).preview(
            list(selection.folder_ids), selection.start, selection.end, selection.destination
        )

    def run_archive(self, selection: ArchiveSelection, *, progress=None, job_id: str | None = None) -> ArchiveRunResult:
        require_destination_writable(selection.destination)
        selection.destination.mkdir(parents=True, exist_ok=True)
        # Probe the actual archive root as well; this closes parent-ACL/race differences.
        require_destination_writable(selection.destination)
        engine = ArchiveJobEngine(self.provider, selection.destination, progress=progress)
        self.active_engine = engine
        job_id = job_id or str(uuid.uuid4())
        try:
            items = tuple(engine.run(list(selection.folder_ids), selection.start, selection.end, job_id=job_id))
        finally:
            self.active_engine = None
        viewer_record = provision_portable_viewer(selection.destination, self.portable_viewer_source)
        if self.registry:
            self.registry.register(selection.destination, opened=False)
        db = connect(selection.destination)
        try:
            job = db.execute('SELECT status,stop_reason,discovered_count,processed_count,verified_count,failed_count FROM archive_jobs WHERE job_id=?', (job_id,)).fetchone()
            job_status = job['status'] if job else 'INTERRUPTED'
            stop_reason = (job['stop_reason'] or '') if job else 'job_state_missing'
            discovered_count = int(job['discovered_count'] or 0) if job else 0
            processed_count = int(job['processed_count'] or 0) if job else 0
            verified_count = int(job['verified_count'] or 0) if job else 0
            failed_count = int(job['failed_count'] or 0) if job else 0
            skipped_count = int(db.execute(
                "SELECT COUNT(*) AS count FROM archive_job_items WHERE job_id=? AND status='SKIPPED_VERIFIED'", (job_id,)
            ).fetchone()['count'] or 0) if job else 0
            archive_size_bytes = int(db.execute("SELECT COALESCE(SUM(mime_size),0) AS size FROM messages WHERE verification_status='VERIFIED'").fetchone()['size'] or 0)
        finally:
            db.close()
        return ArchiveRunResult(
            job_id=job_id,
            archive_root=selection.destination,
            items=items,
            discovered=discovered_count,
            processed=processed_count,
            verified=verified_count,
            skipped=skipped_count,
            failed=failed_count,
            archive_size_bytes=archive_size_bytes,
            cancelled=job_status == 'CANCELLED' or any(status == 'CANCELLED' for _, status in items),
            status=job_status,
            stop_reason=stop_reason,
            interrupted=job_status == 'INTERRUPTED',
            portable_viewer_ready=viewer_record is not None,
        )

    def cancel_archive(self) -> None:
        if self.active_engine:
            self.active_engine.cancel()

    def cleanup_plan(self, archive_root) -> CleanupPlan:
        return CleanupPlanner(archive_root).build()

    def execute_cleanup(self, archive_root, archive_ids, *, cleanup_provider, metadata=None):
        # Separate provider is intentional: production UI obtains Mail.ReadWrite only after explicit cleanup consent.
        if not cleanup_provider.get_capabilities().get('cleanup'):
            raise PermissionError('cleanup provider lacks mailbox write capability')
        started = datetime.now(timezone.utc).isoformat()
        service = CleanupService(cleanup_provider, archive_root)
        results = service.move_verified(list(archive_ids))
        report_metadata = dict(metadata or {})
        report_metadata.setdefault('cleanup_start', started)
        report_metadata.setdefault('cleanup_job_id', service.last_job_id)
        write_cleanup_report(archive_root, results, report_metadata)
        return results

    def verify_archive(self, archive_root):
        return ArchiveIntegrityVerifier(archive_root).verify()

    def open_archive(self, archive_root, *, open_browser=True):
        if self.registry:
            self.registry.register(archive_root)
        return launch_archive(archive_root, open_browser=open_browser)
