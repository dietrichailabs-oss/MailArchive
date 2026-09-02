from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from mailarchive.cleanup.eligibility import CleanupEligibilityService
from mailarchive.archive.manifest import ManifestStore


QUOTA_NOTICE = (
    'Messages will be moved to Deleted Items. Your organization may continue counting these '
    'messages toward mailbox storage until Deleted Items is emptied or retention policies remove them.'
)


@dataclass(frozen=True)
class CleanupPlan:
    archive_ids: tuple[str, ...]
    verified_eligible_count: int
    date_start: str | None
    date_end: str | None
    folders: tuple[str, ...]
    action: str = 'Move verified archived messages to Deleted Items'
    permanent_delete: bool = False
    quota_notice: str = QUOTA_NOTICE
    cleanup_allowed: bool = True
    blocked_reason: str | None = None


class CleanupPlanner:
    def __init__(self, root):
        self.root = Path(root)

    def build(self) -> CleanupPlan:
        manifest = ManifestStore(self.root).load()
        eligibility = CleanupEligibilityService(self.root)
        blocked_reason = eligibility.archive_cleanup_block_reason()
        eligible = () if blocked_reason else tuple(eligibility.eligible_archive_ids())
        date_range = manifest.get('selected_date_range') or {}
        folder_details = manifest.get('selected_folder_details') or ()
        folder_names = tuple(
            str(row.get('name') or row.get('id'))
            for row in folder_details
            if isinstance(row, dict) and (row.get('name') or row.get('id'))
        )
        if not folder_names:
            folder_names = tuple(manifest.get('selected_folders') or ())
        return CleanupPlan(
            archive_ids=eligible,
            verified_eligible_count=len(eligible),
            date_start=date_range.get('start'),
            date_end=date_range.get('end'),
            folders=folder_names,
            cleanup_allowed=not bool(blocked_reason),
            blocked_reason=blocked_reason,
        )
