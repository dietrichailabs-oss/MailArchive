import importlib.util
from pathlib import Path
import tomllib
import pytest


def load_script():
    path = Path(__file__).resolve().parents[2] / 'scripts' / 'validate_release_prerequisites.py'
    spec = importlib.util.spec_from_file_location('validate_release_prerequisites', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def repository_license() -> Path:
    return Path(__file__).resolve().parents[2] / 'LICENSE.txt'


def test_release_build_rejects_engineering_placeholder_client_id():
    mod = load_script()
    with pytest.raises(ValueError, match='microsoft_entra_public_client_id_missing_or_unapproved'):
        mod.validate(
            client_id='00000000-0000-0000-0000-000000000001',
            license_path=repository_license(),
            license_expression=mod.APPROVED_FIRST_PARTY_LICENSE_EXPRESSION,
            engineering=False,
        )


def test_release_build_rejects_other_well_formed_client_id():
    mod = load_script()
    with pytest.raises(ValueError, match='microsoft_entra_public_client_id_missing_or_unapproved'):
        mod.validate(
            client_id='11111111-2222-4333-8444-555555555555',
            license_path=repository_license(),
            license_expression=mod.APPROVED_FIRST_PARTY_LICENSE_EXPRESSION,
            engineering=False,
        )


def test_release_build_rejects_missing_first_party_license():
    mod = load_script()
    with pytest.raises(ValueError, match='first_party_license_text_missing'):
        mod.validate(
            client_id=mod.EXPECTED_MAILARCHIVE_PUBLIC_CLIENT_ID,
            license_path=None,
            license_expression=mod.APPROVED_FIRST_PARTY_LICENSE_EXPRESSION,
            engineering=False,
        )


def test_release_build_rejects_tampered_first_party_license(tmp_path):
    mod = load_script()
    license_file = tmp_path / 'LICENSE.txt'
    license_file.write_text(repository_license().read_text(encoding='utf-8') + '\nmodified\n', encoding='utf-8')
    with pytest.raises(ValueError, match='first_party_license_text_unapproved'):
        mod.validate(
            client_id=mod.EXPECTED_MAILARCHIVE_PUBLIC_CLIENT_ID,
            license_path=license_file,
            license_expression=mod.APPROVED_FIRST_PARTY_LICENSE_EXPRESSION,
            engineering=False,
        )


def test_engineering_build_records_but_allows_incomplete_prerequisites():
    mod = load_script()
    record = mod.validate(
        client_id='00000000-0000-0000-0000-000000000001',
        license_path=None,
        license_expression='',
        engineering=True,
    )
    assert record['engineering_build'] is True
    assert record['qa_release_prerequisites_satisfied'] is False
    assert 'microsoft_entra_public_client_id_missing_or_unapproved' in record['blocking_reasons']


def test_release_prerequisites_pass_with_approved_client_and_license():
    mod = load_script()
    record = mod.validate(
        client_id=mod.EXPECTED_MAILARCHIVE_PUBLIC_CLIENT_ID,
        license_path=repository_license(),
        license_expression=mod.APPROVED_FIRST_PARTY_LICENSE_EXPRESSION,
        engineering=False,
    )
    assert record['qa_release_prerequisites_satisfied'] is True
    assert record['microsoft_entra_client_configured'] is True
    assert record['first_party_license_declared'] is True
    assert record['first_party_license_sha256'] == mod.APPROVED_FIRST_PARTY_LICENSE_SHA256
    assert record['blocking_reasons'] == []


def test_repository_license_metadata_matches_approved_license():
    mod = load_script()
    root = Path(__file__).resolve().parents[2]
    metadata = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    assert metadata['license'] == mod.APPROVED_FIRST_PARTY_LICENSE_EXPRESSION
    assert 'LICENSE.txt' in metadata['license-files']
    assert mod.normalized_text_sha256(root / 'LICENSE.txt') == mod.APPROVED_FIRST_PARTY_LICENSE_SHA256
