from __future__ import annotations

from pathlib import Path
import argparse
import hashlib
import json
import re

BASE_ALLOWED = {
    'MailArchive.exe',
    'Open Archive.exe',
    'SBOM.json',
    'LICENSES.json',
    'THIRD_PARTY_NOTICES.txt',
    'THIRD_PARTY_LICENSES.txt',
    'LICENSE.txt',
    'VERSION.json',
    'README.txt',
}
FORBIDDEN_NAMES = {'.git', '__pycache__', '.pytest_cache', 'tests', 'test', 'logs', 'checkpoints', '.venv', 'venv'}
SENSITIVE_PATTERNS = [
    re.compile(rb'Bearer\s+[A-Za-z0-9._~+/-]{24,}', re.I),
    re.compile(rb'(?i)refresh_token["\'\s:=]+[A-Za-z0-9._~+/-]{24,}'),
]


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest().upper()


def inspect(stage: Path):
    files = [p for p in stage.rglob('*') if p.is_file()]
    rels = {p.relative_to(stage).as_posix() for p in files}
    missing = sorted(BASE_ALLOWED - rels)
    unexpected = sorted(rels - BASE_ALLOWED)
    if missing or unexpected:
        raise SystemExit(f'PACKAGE_ALLOWLIST_FAIL missing={missing} unexpected={unexpected}')
    for path in files:
        parts = {part.casefold() for part in path.relative_to(stage).parts}
        if parts & FORBIDDEN_NAMES:
            raise SystemExit(f'FORBIDDEN_PACKAGE_PATH:{path}')
        raw = path.read_bytes()
        for pattern in SENSITIVE_PATTERNS:
            if pattern.search(raw):
                raise SystemExit(f'POTENTIAL_SECRET_IN_PACKAGE:{path.name}')
    manifest = {
        'files': [
            {'path': rel, 'size': (stage / rel).stat().st_size, 'sha256': sha256(stage / rel)}
            for rel in sorted(rels)
        ]
    }
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('stage')
    parser.add_argument('--manifest', required=True)
    args = parser.parse_args(argv)
    manifest = inspect(Path(args.stage))
    Path(args.manifest).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding='utf-8')
    print(f'PACKAGE_ALLOWLIST_PASS files={len(manifest["files"])}')


if __name__ == '__main__':
    main()
