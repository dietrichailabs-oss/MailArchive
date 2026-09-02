from __future__ import annotations

from pathlib import Path
import os

from mailarchive.platform.windows import dpapi


class ProtectedTokenCacheStore:
    def __init__(self, path: str | Path, *, protector=dpapi):
        self.path = Path(path)
        self.protector = protector

    def load(self) -> str:
        if not self.path.exists():
            return ''
        encrypted = self.path.read_bytes()
        if not encrypted:
            return ''
        return self.protector.unprotect(encrypted).decode('utf-8')

    def save(self, serialized_cache: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = self.protector.protect(serialized_cache.encode('utf-8'))
        tmp = self.path.with_suffix(self.path.suffix + '.tmp')
        tmp.write_bytes(encrypted)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
