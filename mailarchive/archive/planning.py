from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import tempfile
import re
import json
import sqlite3


class ArchiveDestinationError(OSError):
    """The selected archive destination cannot safely accept archive writes."""


_ARCHIVE_MARKERS = ('archive.db', 'manifest.json', 'manifest.journal.jsonl', 'archive_info.json')


def archive_folder_name(start: str | None, end: str | None) -> str:
    """Return a stable, filesystem-safe archive folder name for a date selection.

    The UI asks users for a *parent* folder (for example ``Desktop\\Mail Archives``),
    while the archive itself lives one level below it. Stable naming means a repeated
    run of the same date range can safely target the same archive and rely on the
    engine's verified-message deduplication instead of silently creating a second
    archive containing the same mail.
    """
    start_day = (start or '').strip()[:10]
    end_day = (end or '').strip()[:10]
    if start_day and end_day:
        raw = f'{start_day}_to_{end_day}'
    elif start_day:
        raw = f'from_{start_day}'
    elif end_day:
        raw = f'through_{end_day}'
    else:
        raw = 'all_mail'
    # Dates are already constrained by the UI/controller, but keep this helper safe
    # if it is ever called by another front end.
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', raw).strip(' ._')
    return safe or 'mail_archive'


def _account_key(metadata: dict | None) -> str:
    metadata = metadata if isinstance(metadata, dict) else {}
    value = metadata.get('account_id') or metadata.get('principal_hint') or ''
    return str(value).strip().casefold()


def _read_archive_identity(path: Path) -> tuple[str | None, str | None, str, bool]:
    """Read a lightweight archive identity without modifying the directory.

    The SQLite job ledger is authoritative. JSON files are checked only for structural
    consistency so a corrupt/ambiguous archive is never silently merged into. A valid
    interrupted archive may legitimately have DB + manifest journal but no compacted
    ``archive_info.json`` yet.
    """
    db_path = path / 'archive.db'
    if not db_path.is_file():
        return None, None, '', False
    try:
        uri = db_path.resolve().as_uri() + '?mode=ro'
        db = sqlite3.connect(uri, uri=True)
        db.row_factory = sqlite3.Row
        try:
            rows = db.execute(
                'SELECT DISTINCT start_date,end_date FROM archive_jobs ORDER BY start_date,end_date'
            ).fetchall()
            if len(rows) != 1:
                return None, None, '', False
            start = rows[0]['start_date'] or None
            end = rows[0]['end_date'] or None
            row = db.execute(
                "SELECT value FROM archive_metadata WHERE key='source_account'"
            ).fetchone()
            account_key = ''
            if row:
                try:
                    account_key = _account_key(json.loads(row['value']))
                except Exception:
                    return None, None, '', False
            verified_count = int(db.execute(
                "SELECT COUNT(*) FROM messages WHERE verification_status='VERIFIED'"
            ).fetchone()[0])
        finally:
            db.close()
    except Exception:
        return None, None, '', False

    manifest_path = path / 'manifest.json'
    journal_path = path / 'manifest.journal.jsonl'
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            if not isinstance(manifest, dict) or not isinstance(manifest.get('messages'), dict):
                return None, None, '', False
            date_range = manifest.get('selected_date_range')
            if isinstance(date_range, dict):
                manifest_range = (date_range.get('start') or None, date_range.get('end') or None)
                if manifest_range != (start, end):
                    return None, None, '', False
            manifest_account = _account_key(manifest.get('source_account'))
            if manifest_account and account_key and manifest_account != account_key:
                return None, None, '', False
        except Exception:
            return None, None, '', False
    elif verified_count and not journal_path.is_file():
        # A verified DB row without either durable manifest representation is damaged.
        return None, None, '', False

    info_path = path / 'archive_info.json'
    if info_path.exists():
        try:
            info = json.loads(info_path.read_text(encoding='utf-8'))
            if not isinstance(info, dict):
                return None, None, '', False
            date_range = info.get('selected_date_range')
            if isinstance(date_range, dict):
                info_range = (date_range.get('start') or None, date_range.get('end') or None)
                if info_range != (start, end):
                    return None, None, '', False
            info_account = _account_key(info.get('source_account'))
            if info_account and account_key and info_account != account_key:
                return None, None, '', False
        except Exception:
            return None, None, '', False
    return start, end, account_key, True

def _existing_archive_matches(
    path: Path,
    start: str | None,
    end: str | None,
    account_metadata: dict | None,
) -> bool:
    if not path.is_dir() or not any((path / marker).exists() for marker in _ARCHIVE_MARKERS):
        return False
    # archive.db is the durable job/verification ledger. A few loose JSON/journal files are
    # not sufficient proof that a directory is safe to merge into.
    if not (path / 'archive.db').is_file():
        return False
    existing_start, existing_end, existing_account, identity_valid = _read_archive_identity(path)
    if not identity_valid:
        return False
    requested = ((start or None), (end or None))
    if (existing_start, existing_end) != requested:
        return False
    requested_account = _account_key(account_metadata)
    if requested_account:
        # Fail closed when an authenticated account is known but the old archive's provenance
        # is absent/corrupt. Mixing two mailboxes is worse than allocating a new sibling.
        return bool(existing_account) and existing_account == requested_account
    return True


def _directory_is_empty(path: Path) -> bool:
    try:
        return path.is_dir() and not any(path.iterdir())
    except OSError:
        return False


def resolve_archive_root(
    parent,
    start: str | None,
    end: str | None,
    *,
    account_metadata: dict | None = None,
) -> Path:
    """Resolve the exact portable archive root below a user-selected parent.

    A prior root is reused only when its read-only durable metadata proves it belongs
    to the same date range and, when known, the same mailbox account. Unrelated,
    corrupt, ambiguous, or non-empty directories are never overwritten.
    """
    parent = Path(parent).expanduser()
    base = parent / archive_folder_name(start, end)
    for suffix in range(1, 10_000):
        candidate = base if suffix == 1 else parent / f'{base.name}_{suffix}'
        if not candidate.exists() or _directory_is_empty(candidate):
            return candidate
        if _existing_archive_matches(candidate, start, end, account_metadata):
            return candidate
    raise ArchiveDestinationError('could not allocate a safe archive folder name')

def _nearest_existing_path(destination: Path) -> Path:
    probe = destination
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return probe


def probe_destination_writable(destination) -> tuple[bool, str]:
    """Probe filesystem writeability without leaving archive/user data behind.

    Existing destination directories are probed directly. For a destination that does
    not yet exist, the nearest existing parent is probed because creating the archive
    directory will require write access there.
    """
    destination = Path(destination).expanduser()
    if destination.exists() and not destination.is_dir():
        return False, 'selected archive destination exists but is not a directory'
    probe = destination if destination.exists() else _nearest_existing_path(destination)
    if not probe.exists() or not probe.is_dir():
        return False, 'no usable parent directory exists for the selected destination'
    try:
        fd, name = tempfile.mkstemp(prefix='.mailarchive-write-probe-', dir=probe)
        try:
            os.write(fd, b'MailArchive destination write probe\n')
            os.fsync(fd)
        finally:
            os.close(fd)
        os.unlink(name)
    except Exception as exc:
        try:
            if 'name' in locals() and os.path.exists(name):
                os.unlink(name)
        except Exception:
            pass
        return False, f'destination is not writable: {type(exc).__name__}: {exc}'
    return True, ''


def require_destination_writable(destination) -> None:
    ok, detail = probe_destination_writable(destination)
    if not ok:
        raise ArchiveDestinationError(detail)


@dataclass(frozen=True)
class ArchivePreview:
    folders: tuple[str, ...]
    start: str | None
    end: str | None
    destination: str
    message_count: int
    estimated_bytes: int | None
    available_bytes: int
    destination_writable: bool = True
    destination_error: str = ''
    include_attachments: bool = True
    cleanup_behavior: str = 'Archive Only — Keep Original Messages'

    @property
    def likely_has_space(self) -> bool | None:
        if self.estimated_bytes is None:
            return None
        # 15% working/headroom overhead, minimum 64 MiB.
        required = max(self.estimated_bytes + 64 * 1024 * 1024, int(self.estimated_bytes * 1.15))
        return self.available_bytes >= required


class ArchivePlanner:
    def __init__(self, provider):
        self.provider = provider

    def preview(self, folder_ids: list[str], start: str | None, end: str | None, destination) -> ArchivePreview:
        count = 0
        known_size = 0
        all_sizes_known = True
        for message in self.provider.discover_messages(folder_ids, start, end):
            count += 1
            if message.size_hint is None:
                all_sizes_known = False
            else:
                known_size += max(0, int(message.size_hint))
        destination = Path(destination).expanduser()
        probe = _nearest_existing_path(destination)
        available = shutil.disk_usage(probe).free
        writable, error = probe_destination_writable(destination)
        estimate = known_size if all_sizes_known else (known_size if count and known_size else None)
        return ArchivePreview(
            tuple(folder_ids), start, end, str(destination), count, estimate, available,
            destination_writable=writable, destination_error=error,
        )
