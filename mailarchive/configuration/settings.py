from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import os
import tempfile
import re


_WINDOW_GEOMETRY_RE = re.compile(r'^(?P<w>\d+)x(?P<h>\d+)(?P<x>[+-]\d+)(?P<y>[+-]\d+)$')


def valid_window_geometry(value: str) -> str:
    """Return a bounded Tk geometry string or an empty string for invalid/corrupt settings."""
    value = str(value or '').strip()
    match = _WINDOW_GEOMETRY_RE.fullmatch(value)
    if not match:
        return ''
    width = int(match.group('w'))
    height = int(match.group('h'))
    if not (640 <= width <= 7680 and 480 <= height <= 4320):
        return ''
    return value


@dataclass
class AppSettings:
    last_archive_destination: str = ''
    preferred_folder_ids: list[str] = field(default_factory=list)
    window_geometry: str = ''
    last_account_hint: str = ''


class SettingsStore:
    """Non-secret user preferences only. Authentication material lives in protected token storage."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            allowed = {k: raw[k] for k in AppSettings.__dataclass_fields__ if k in raw}
            return AppSettings(**allowed)
        except Exception:
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='settings.', suffix='.tmp', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(asdict(settings), handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise


def application_data_dir() -> Path:
    base = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
    if base:
        return Path(base) / 'Dietrich AI Labs' / 'MailArchive'
    return Path.home() / '.mailarchive'


def default_archive_parent() -> Path:
    desktop = Path.home() / 'Desktop'
    return desktop / 'Mail Archives'
