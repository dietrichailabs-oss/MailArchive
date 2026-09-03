from __future__ import annotations

from pathlib import Path
import hashlib
import os
import re

from mailarchive.archive.hashing import sha256_bytes

_RESERVED = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}


def sanitize_filename(name: str, index: int = 0) -> str:
    name = (name or f'attachment-{index}').replace('\\', '_').replace('/', '_')
    name = re.sub(r'[<>:"|?*\x00-\x1f]', '_', name)
    while '..' in name:
        name = name.replace('..', '_')
    name = name.strip(' .')
    stem = Path(name).stem.upper()
    if stem in _RESERVED:
        name = '_' + name
    if not name:
        name = f'attachment-{index}'
    if len(name) > 180:
        suffix = Path(name).suffix[:20]
        base = Path(name).stem[:150]
        name = base + '_' + hashlib.sha256(name.encode('utf-8', 'replace')).hexdigest()[:12] + suffix
    return name


def normalize_content_id(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().strip('<>').strip()
    return value or None


class AttachmentStore:
    def __init__(self, root):
        self.root = Path(root)

    def extract(self, archive_id, msg):
        out = []
        target = self.root / 'attachments' / archive_id
        target.mkdir(parents=True, exist_ok=True)
        used = set()
        idx = 0
        for part in msg.walk():
            disposition = part.get_content_disposition()
            filename = part.get_filename()
            content_id = normalize_content_id(part.get('Content-ID'))
            # Preserve normal attachments and inline MIME resources (CID/filename-bearing parts).
            if disposition != 'attachment' and not filename and not content_id:
                continue
            if part.is_multipart():
                continue
            idx += 1
            original = filename or (f'inline-{idx}' if content_id else f'attachment-{idx}')
            safe = sanitize_filename(original, idx)
            base = safe
            n = 1
            while safe.lower() in used:
                p = Path(base)
                safe = f'{p.stem}_{n}{p.suffix}'
                n += 1
            used.add(safe.lower())
            data = part.get_payload(decode=True) or b''
            path = target / safe
            tmp = path.with_suffix(path.suffix + '.tmp')
            tmp.write_bytes(data)
            os.replace(tmp, path)
            rel = str(path.relative_to(self.root)).replace('\\', '/')
            out.append({
                'filename': original,
                'sanitized_filename': safe,
                'mime_type': part.get_content_type(),
                'size': len(data),
                'sha256': sha256_bytes(data),
                'relative_path': rel,
                'extraction_status': 'EXTRACTED',
                'content_id': content_id,
            })
        return out
