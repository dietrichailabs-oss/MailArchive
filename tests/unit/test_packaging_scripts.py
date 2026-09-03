from pathlib import Path


def test_build_windows_preserves_iscc_candidates_as_array():
    script = (Path(__file__).resolve().parents[2] / 'packaging' / 'build_windows.ps1').read_text(encoding='utf-8')
    marker = '$IsccCandidates = @(\n    @('
    assert marker in script
    assert '$ISCC = $IsccCandidates[0]' in script


def test_windows_clean_machine_gate_waits_for_every_gui_process():
    script = (Path(__file__).resolve().parents[2] / 'packaging' / 'windows_clean_machine_gate.ps1').read_text(encoding='utf-8')
    assert 'function Invoke-WaitedProcess' in script
    assert '$process.WaitForExit(' in script
    for executable in ('$Installer', '$MainExe', '$ViewerExe', '$Uninstaller'):
        assert f'-FilePath {executable}' in script
    assert '& $Installer ' not in script
    assert '& $MainExe ' not in script
    assert '& $ViewerExe ' not in script
    assert '& $Uninstaller ' not in script


def test_windows_packaging_version_surfaces_match_python_package_version():
    from mailarchive import __version__

    root = Path(__file__).resolve().parents[2]
    for relative in (
        'packaging/build_windows.ps1',
        'packaging/windows_clean_machine_gate.ps1',
        'packaging/MailArchive.iss',
        '.github/workflows/engineering-windows-gate.yml',
    ):
        assert __version__ in (root / relative).read_text(encoding='utf-8'), relative


def test_release_candidate_is_windows_11_x64_and_not_engineering_placeholder_build():
    root = Path(__file__).resolve().parents[2]
    build = (root / 'packaging' / 'build_windows.ps1').read_text(encoding='utf-8')
    gate = (root / 'packaging' / 'windows_clean_machine_gate.ps1').read_text(encoding='utf-8')
    assert 'platform="Windows 11 x64"' in build
    assert 'supported_platform="Windows 11 x64"' in build
    assert 'release_candidate=$true' in build
    assert 'RC_BUILD_MUST_NOT_USE_ENGINEERING_PLACEHOLDERS' in gate
    assert '-EngineeringBuild' not in gate
    assert "supported_platform='Windows 11 x64'" in gate


def test_windows_upgrade_gate_requires_real_previous_installer_artifact():
    script = (Path(__file__).resolve().parents[2] / 'packaging' / 'windows_clean_machine_gate.ps1').read_text(encoding='utf-8')
    assert 'PREVIOUS_INSTALLER_REQUIRED_FOR_TRUE_UPGRADE' in script
    assert 'previous_installer_sha256=$PreviousInstallerSha256' in script
    assert 'upgrade_source="immutable_previous_qa_pass_installer_artifact"' in script
    assert 'Copy-Item (Join-Path $BuildRoot "stage") $UpgradeStage -Recurse' not in script
    assert 'PRIOR_INSTALLER_BUILD_FAILED' not in script


def test_windows_workflow_uses_qa_passed_rc2_installer():
    workflow = (Path(__file__).resolve().parents[2] / '.github' / 'workflows' / 'engineering-windows-gate.yml').read_text(encoding='utf-8')
    assert 'actions/download-artifact@v4' in workflow
    assert 'run-id: 33706133050' in workflow
    assert 'MailArchive_1.0.0-rc2_Setup.exe' in workflow
    assert '80BA101BF6702295E48E79AB7E627FBFB52DDD866C7D00788D5DCFE28A8398EB' in workflow
    assert '-PreviousVersion "1.0.0-rc2"' in workflow
    assert '-PreviousInstallerPath "${{ steps.previous-installer.outputs.path }}"' in workflow
    assert 'MailArchive-1.0.0-rc6-Windows-Engineering-Gate' in workflow
    assert 'AUTHENTICODE_STATUS.json' in workflow


def test_windows_build_uses_repository_release_prerequisites():
    root = Path(__file__).resolve().parents[2]
    build = (root / 'packaging' / 'build_windows.ps1').read_text(encoding='utf-8')
    gate = (root / 'packaging' / 'windows_clean_machine_gate.ps1').read_text(encoding='utf-8')
    assert '[switch]$EngineeringBuild' in build
    assert 'resources\\microsoft_app.json' in build
    assert 'LICENSE.txt' in build
    assert 'LicenseRef-Dietrich-AI-Labs-Freeware-1.0' in build
    assert 'validate_release_prerequisites.py' in build
    assert 'qa_release_prerequisites_satisfied' in build
    assert 'RELEASE_PREREQUISITES_NOT_SATISFIED' in gate


def test_windows_workflow_preserves_release_prerequisite_evidence():
    workflow = (Path(__file__).resolve().parents[2] / '.github' / 'workflows' / 'engineering-windows-gate.yml').read_text(encoding='utf-8')
    assert 'build-windows/BUILD_PREREQUISITES.json' in workflow


def test_windows_binaries_and_setup_use_deterministically_generated_mailarchive_icon(tmp_path):
    root = Path(__file__).resolve().parents[2]
    from scripts.generate_windows_icon import build_ico
    first = build_ico()
    second = build_ico()
    assert first == second
    assert len(first) > 1024
    assert first[:4] == b'\x00\x00\x01\x00'
    assert int.from_bytes(first[4:6], 'little') == 7
    build = (root / 'packaging' / 'build_windows.ps1').read_text(encoding='utf-8')
    assert 'generate_windows_icon.py' in build
    assert build.count('--icon $IconPath') == 2
    assert '/DSetupIconPath=$IconPath' in build
    installer = (root / 'packaging' / 'MailArchive.iss').read_text(encoding='utf-8')
    assert 'SetupIconFile={#SetupIconPath}' in installer


def test_installer_requires_first_party_license_file():
    root = Path(__file__).resolve().parents[2]
    installer = (root / 'packaging' / 'MailArchive.iss').read_text(encoding='utf-8')
    license_line = next(line for line in installer.splitlines() if 'StageDir}\\LICENSE.txt' in line)
    assert 'skipifsourcedoesntexist' not in license_line
