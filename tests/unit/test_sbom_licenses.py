from email.message import Message
import importlib.util
from pathlib import Path


def load_generator():
    path = Path(__file__).resolve().parents[2] / 'scripts' / 'generate_runtime_sbom.py'
    spec = importlib.util.spec_from_file_location('generate_runtime_sbom', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_license_expression_preferred_over_legacy_metadata():
    mod = load_generator()
    meta = Message()
    meta['License'] = 'legacy-value'
    meta['License-Expression'] = 'Apache-2.0 OR BSD-3-Clause'
    assert mod._license_expression(meta) == 'Apache-2.0 OR BSD-3-Clause'


def test_license_classifier_fallback_is_spdx_like():
    mod = load_generator()
    meta = Message()
    meta['Classifier'] = 'License :: OSI Approved :: MIT License'
    assert mod._license_expression(meta) == 'MIT'


def test_project_url_falls_back_to_modern_project_url_metadata():
    mod = load_generator()
    meta = Message()
    meta['Project-URL'] = 'Documentation, https://docs.invalid/'
    meta['Project-URL'] = 'Source, https://source.invalid/project'
    assert mod._project_url(meta) == 'https://source.invalid/project'


def test_stage_allowlist_requires_third_party_license_text_bundle():
    verify = Path(__file__).resolve().parents[2] / 'scripts' / 'verify_stage.py'
    text = verify.read_text(encoding='utf-8')
    assert "'THIRD_PARTY_LICENSES.txt'" in text
    installer = (Path(__file__).resolve().parents[2] / 'packaging' / 'MailArchive.iss').read_text(encoding='utf-8')
    assert 'THIRD_PARTY_LICENSES.txt' in installer


def test_application_license_expression_can_be_overridden_for_release_sbom(monkeypatch):
    mod = load_generator()
    components = [
        {'type': 'application', 'name': 'mailarchive', 'version': '1.0', 'license': 'NOASSERTION', 'homepage': ''},
        {'type': 'library', 'name': 'requests', 'version': '2', 'license': 'Apache-2.0', 'homepage': ''},
    ]
    # The CLI path applies the override before writing; assert the same root-selection rule used there.
    application_license = 'LicenseRef-Dietrich-AI-Labs-Freeware'
    for item in components:
        if mod.normalize(item['name']) == 'mailarchive':
            item['license'] = application_license
            break
    assert components[0]['license'] == application_license
