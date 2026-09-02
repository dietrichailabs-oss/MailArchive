from __future__ import annotations

from pathlib import Path
import os
import shutil
import sys
import tempfile

from mailarchive.archive.hashing import sha256_file
from mailarchive.archive.manifest import ManifestStore


PORTABLE_VIEWER_NAME = 'Open Archive.exe'


def discover_installed_viewer() -> Path | None:
    override = os.environ.get('MAILARCHIVE_PORTABLE_VIEWER_EXE', '').strip()
    if override:
        path = Path(override).expanduser().resolve()
        return path if path.is_file() else None
    if getattr(sys, 'frozen', False):
        path = Path(sys.executable).resolve().parent / PORTABLE_VIEWER_NAME
        return path if path.is_file() else None
    return None


def provision_portable_viewer(archive_root, source: str | Path | None = None) -> dict | None:
    root = Path(archive_root).resolve()
    source_path = Path(source).resolve() if source else discover_installed_viewer()
    if source_path is None or not source_path.is_file():
        return None
    target = root / PORTABLE_VIEWER_NAME
    fd, tmp_name = tempfile.mkstemp(prefix='open-archive.', suffix='.tmp', dir=root)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        shutil.copy2(source_path, tmp)
        os.replace(tmp, target)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise
    record = {
        'relative_path': PORTABLE_VIEWER_NAME,
        'sha256': sha256_file(target),
        'size': target.stat().st_size,
    }
    ManifestStore(root).update_archive_metadata({'portable_viewer': record})
    return record
