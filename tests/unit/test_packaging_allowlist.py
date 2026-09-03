import importlib.util
from pathlib import Path


def load_script(name):
    path = Path(__file__).parents[2] / 'scripts' / name
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_stage_allowlist_accepts_only_expected_runtime_files(tmp_path):
    mod = load_script('verify_stage.py')
    for name in mod.BASE_ALLOWED:
        (tmp_path / name).write_bytes(b'clean')
    manifest = mod.inspect(tmp_path)
    assert len(manifest['files']) == len(mod.BASE_ALLOWED)
    assert 'LICENSE.txt' in mod.BASE_ALLOWED


def test_stage_allowlist_rejects_source_or_extra_files(tmp_path):
    mod = load_script('verify_stage.py')
    for name in mod.BASE_ALLOWED:
        (tmp_path / name).write_bytes(b'clean')
    (tmp_path / 'source.py').write_text('oops', encoding='utf-8')
    try:
        mod.inspect(tmp_path)
    except SystemExit as exc:
        assert 'unexpected' in str(exc)
    else:
        raise AssertionError('unexpected source file was accepted')


def test_stage_allowlist_rejects_missing_first_party_license(tmp_path):
    mod = load_script('verify_stage.py')
    for name in mod.BASE_ALLOWED - {'LICENSE.txt'}:
        (tmp_path / name).write_bytes(b'clean')
    try:
        mod.inspect(tmp_path)
    except SystemExit as exc:
        assert 'LICENSE.txt' in str(exc)
    else:
        raise AssertionError('package without first-party license was accepted')
