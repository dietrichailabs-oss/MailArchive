from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class ManifestStore:
    """Crash-safe scalable manifest.

    Per-message verification commits to an fsynced append-only journal. A valid manifest.json
    is atomically compacted at job boundaries. load() always replays the journal, so a verified
    message cannot disappear from manifest state merely because the process died before compaction.
    """

    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / 'manifest.json'
        self.journal_path = self.root / 'manifest.journal.jsonl'
        self.info_path = self.root / 'archive_info.json'

    def load(self):
        if self.path.exists():
            try:
                doc = json.loads(self.path.read_text(encoding='utf-8'))
            except Exception:
                doc = {'archive_format_version': 1, 'messages': {}}
        else:
            doc = {'archive_format_version': 1, 'messages': {}}
        if not isinstance(doc, dict):
            doc = {'archive_format_version': 1, 'messages': {}}
        doc.setdefault('archive_format_version', 1)
        messages = doc.setdefault('messages', {})
        if self.journal_path.exists():
            # Invalid/truncated final line is ignored. It cannot correspond to a DB VERIFIED row
            # because DB promotion happens only after this append returns successfully and fsyncs.
            with self.journal_path.open('r', encoding='utf-8', errors='strict') as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                        archive_id = entry['archive_id']
                        record = entry['record']
                    except Exception:
                        continue
                    if isinstance(archive_id, str) and isinstance(record, dict):
                        messages[archive_id] = record
        return doc

    def _atomic_json(self, path: Path, doc: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(doc, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise

    def upsert_verified(self, archive_id, record):
        self.root.mkdir(parents=True, exist_ok=True)
        entry = json.dumps({'archive_id': archive_id, 'record': record}, ensure_ascii=False, separators=(',', ':')) + '\n'
        fd = os.open(self.journal_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            payload = entry.encode('utf-8')
            offset = 0
            while offset < len(payload):
                written = os.write(fd, payload[offset:])
                if written <= 0:
                    raise OSError('manifest journal write made no progress')
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)

    def compact(self, metadata: dict | None = None):
        doc = self.load()
        if metadata:
            doc.update(metadata)
        doc.setdefault('archive_format_version', 1)
        self._atomic_json(self.path, doc)
        info = {k: v for k, v in doc.items() if k != 'messages'}
        self._atomic_json(self.info_path, info)
        # manifest.json is durable first. If deletion fails, replaying journal is idempotent.
        try:
            self.journal_path.unlink()
        except FileNotFoundError:
            pass
        return doc

    def update_archive_metadata(self, metadata: dict):
        return self.compact(metadata)
