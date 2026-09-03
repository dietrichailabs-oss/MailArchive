from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import os
import tempfile


class ArchiveRegistry:
    def __init__(self, registry_path):
        self.path = Path(registry_path)

    def _load(self):
        if not self.path.exists():
            return {'archives': []}
        try:
            doc = json.loads(self.path.read_text(encoding='utf-8'))
            return doc if isinstance(doc, dict) and isinstance(doc.get('archives'), list) else {'archives': []}
        except Exception:
            return {'archives': []}

    def _save(self, doc):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='archives.', suffix='.tmp', dir=self.path.parent)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(doc, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)

    def register(self, archive_path, *, opened: bool = True):
        archive_path = str(Path(archive_path).resolve())
        doc = self._load()
        previous = next((item for item in doc['archives'] if item.get('path') == archive_path), {})
        doc['archives'] = [item for item in doc['archives'] if item.get('path') != archive_path]
        entry = {'path': archive_path}
        if previous.get('last_opened'):
            entry['last_opened'] = previous['last_opened']
        if opened:
            entry['last_opened'] = datetime.now(timezone.utc).isoformat()
        doc['archives'].append(entry)
        self._save(doc)

    def remove_from_list(self, archive_path):
        archive_path = str(Path(archive_path).resolve())
        doc = self._load()
        doc['archives'] = [item for item in doc['archives'] if item.get('path') != archive_path]
        self._save(doc)

    def list_archives(self):
        out = []
        for item in self._load()['archives']:
            path = Path(item['path'])
            info = {}
            try:
                info = json.loads((path / 'archive_info.json').read_text(encoding='utf-8'))
            except Exception:
                pass
            out.append({**item, **info, 'exists': path.exists()})
        return out
