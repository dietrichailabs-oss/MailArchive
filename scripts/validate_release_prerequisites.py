from __future__ import annotations

from pathlib import Path
import argparse
import hashlib
import json
import uuid


EXPECTED_MAILARCHIVE_PUBLIC_CLIENT_ID = '86e23ad4-16fe-488a-8e4e-a6e2e741b96f'
APPROVED_FIRST_PARTY_LICENSE_EXPRESSION = 'LicenseRef-Dietrich-AI-Labs-Freeware-1.0'
APPROVED_FIRST_PARTY_LICENSE_SHA256 = '761C343DA3FD6F7E690C559B7AD20A9D684B82AFB1196811F4F025C079E79731'
KNOWN_PLACEHOLDER_CLIENT_IDS = {
    '',
    '00000000-0000-0000-0000-000000000000',
    '00000000-0000-0000-0000-000000000001',
    'replace_with_microsoft_entra_app_client_id',
}
UNDECLARED_LICENSES = {'', 'unknown', 'noassertion', 'none', 'tbd', 'todo'}


def is_real_client_id(value: str) -> bool:
    value = (value or '').strip()
    if value.casefold() in KNOWN_PLACEHOLDER_CLIENT_IDS:
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return parsed.int != 0


def normalized_text_sha256(path: Path) -> str:
    text = path.read_text(encoding='utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    return hashlib.sha256(text.encode('utf-8')).hexdigest().upper()


def validate(*, client_id: str, license_path: str | Path | None, license_expression: str, engineering: bool) -> dict:
    client_id = (client_id or '').strip()
    license_expression = (license_expression or '').strip()
    client_ok = is_real_client_id(client_id) and client_id.casefold() == EXPECTED_MAILARCHIVE_PUBLIC_CLIENT_ID.casefold()
    license_expression_declared = license_expression.casefold() not in UNDECLARED_LICENSES
    license_expression_ok = license_expression == APPROVED_FIRST_PARTY_LICENSE_EXPRESSION
    path = Path(license_path).expanduser().resolve() if license_path else None
    license_file_present = bool(path and path.is_file() and 0 < path.stat().st_size <= 2 * 1024 * 1024)
    license_sha256 = normalized_text_sha256(path) if license_file_present else ''
    license_text_ok = license_file_present and license_sha256 == APPROVED_FIRST_PARTY_LICENSE_SHA256

    reasons = []
    if not client_ok:
        reasons.append('microsoft_entra_public_client_id_missing_or_unapproved')
    if not license_expression_declared or not license_expression_ok:
        reasons.append('first_party_license_expression_missing_or_unapproved')
    if not license_file_present:
        reasons.append('first_party_license_text_missing')
    elif not license_text_ok:
        reasons.append('first_party_license_text_unapproved')

    ready = not reasons
    record = {
        'engineering_build': bool(engineering),
        'qa_release_prerequisites_satisfied': ready,
        'microsoft_entra_client_configured': client_ok,
        'microsoft_entra_client_id_sha256': hashlib.sha256(client_id.encode('utf-8')).hexdigest().upper() if client_ok else '',
        'first_party_license_declared': license_expression_ok and license_text_ok,
        'first_party_license_expression': license_expression if license_expression_ok else 'NOASSERTION',
        'first_party_license_filename': path.name if license_file_present else '',
        'first_party_license_sha256': license_sha256,
        'blocking_reasons': reasons,
    }
    if reasons and not engineering:
        raise ValueError('QA_RELEASE_PREREQUISITES_MISSING:' + ','.join(reasons))
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--client-id', default='')
    parser.add_argument('--first-party-license-path', default='')
    parser.add_argument('--first-party-license-expression', default='')
    parser.add_argument('--engineering', action='store_true')
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        record = validate(
            client_id=args.client_id,
            license_path=args.first_party_license_path or None,
            license_expression=args.first_party_license_expression,
            engineering=args.engineering,
        )
    except ValueError as exc:
        print(str(exc))
        return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True), encoding='utf-8')
    print('QA_RELEASE_PREREQUISITES_PASS' if record['qa_release_prerequisites_satisfied'] else 'ENGINEERING_PREREQUISITES_INCOMPLETE')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
