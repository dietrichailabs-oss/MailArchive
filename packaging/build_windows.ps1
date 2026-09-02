param(
    [string]$Version = "1.0.0-rc1",
    [string]$BuildIdentity = "2026.09.02-rc1",
    [string]$ClientId = $env:MAILARCHIVE_CLIENT_ID,
    [string]$FirstPartyLicensePath = $env:MAILARCHIVE_FIRST_PARTY_LICENSE_PATH,
    [string]$FirstPartyLicenseExpression = $env:MAILARCHIVE_FIRST_PARTY_LICENSE_EXPRESSION,
    [switch]$EngineeringBuild
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

if ([string]::IsNullOrWhiteSpace($ClientId)) {
    $RepoClientConfig = Join-Path $Root "resources\microsoft_app.json"
    if (Test-Path $RepoClientConfig -PathType Leaf) {
        $ClientId = [string]((Get-Content $RepoClientConfig -Raw | ConvertFrom-Json).client_id)
    }
}
if ([string]::IsNullOrWhiteSpace($ClientId) -and $EngineeringBuild) {
    $ClientId = "00000000-0000-0000-0000-000000000001"
}
if ([string]::IsNullOrWhiteSpace($FirstPartyLicensePath)) {
    $RepoLicense = Join-Path $Root "LICENSE.txt"
    if (Test-Path $RepoLicense -PathType Leaf) { $FirstPartyLicensePath = $RepoLicense }
}
if ([string]::IsNullOrWhiteSpace($FirstPartyLicenseExpression)) {
    $FirstPartyLicenseExpression = "LicenseRef-Dietrich-AI-Labs-Freeware-1.0"
}

$BuildRoot = Join-Path $Root "build-windows"
$PyDist = Join-Path $BuildRoot "pyinstaller-dist"
$Stage = Join-Path $BuildRoot "stage"
$InstallerOut = Join-Path $BuildRoot "installer"
$BuildResources = Join-Path $BuildRoot "resources"
Remove-Item $BuildRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $PyDist,$Stage,$InstallerOut,$BuildResources | Out-Null

$IconPath = Join-Path $BuildResources "MailArchive.ico"
python scripts\generate_windows_icon.py $IconPath
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $IconPath)) { throw "ICON_GENERATION_FAILED" }

$PrereqPath = Join-Path $BuildRoot "BUILD_PREREQUISITES.json"
$PrereqArgs = @(
    "scripts\validate_release_prerequisites.py",
    "--client-id", [string]$ClientId,
    "--first-party-license-path", [string]$FirstPartyLicensePath,
    "--first-party-license-expression", [string]$FirstPartyLicenseExpression,
    "--output", $PrereqPath
)
if ($EngineeringBuild) { $PrereqArgs += "--engineering" }
python @PrereqArgs
if ($LASTEXITCODE -ne 0) { throw "QA_RELEASE_PREREQUISITES_FAILED" }
$Prerequisites = Get-Content $PrereqPath -Raw | ConvertFrom-Json

@{client_id=$ClientId;authority="https://login.microsoftonline.com/common";application_type="public_desktop_client"} |
    ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $BuildResources "microsoft_app.json")

python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "TESTS_FAILED" }

python -m PyInstaller --noconfirm --clean --onefile --windowed --name "MailArchive" `
    --icon $IconPath `
    --distpath $PyDist --workpath (Join-Path $BuildRoot "pyi-main") `
    --specpath (Join-Path $BuildRoot "spec-main") `
    --add-data "$BuildResources\microsoft_app.json;resources" mailarchive\app.py
if ($LASTEXITCODE -ne 0) { throw "PYINSTALLER_MAIN_FAILED" }

python -m PyInstaller --noconfirm --clean --onefile --windowed --name "Open Archive" `
    --icon $IconPath `
    --distpath $PyDist --workpath (Join-Path $BuildRoot "pyi-viewer") `
    --specpath (Join-Path $BuildRoot "spec-viewer") mailarchive\viewer\launcher.py
if ($LASTEXITCODE -ne 0) { throw "PYINSTALLER_VIEWER_FAILED" }

Copy-Item (Join-Path $PyDist "MailArchive.exe") $Stage
Copy-Item (Join-Path $PyDist "Open Archive.exe") $Stage

$SbomArgs = @(
    "scripts\generate_runtime_sbom.py",
    "--output", (Join-Path $Stage "SBOM.json"),
    "--licenses", (Join-Path $Stage "LICENSES.json"),
    "--notices", (Join-Path $Stage "THIRD_PARTY_NOTICES.txt"),
    "--license-texts", (Join-Path $Stage "THIRD_PARTY_LICENSES.txt")
)
if (-not [string]::IsNullOrWhiteSpace($FirstPartyLicenseExpression)) {
    $SbomArgs += @("--application-license-expression", $FirstPartyLicenseExpression)
}
python @SbomArgs
if ($LASTEXITCODE -ne 0) { throw "SBOM_GENERATION_FAILED" }
$ResolvedFirstPartyLicense = (Resolve-Path $FirstPartyLicensePath -ErrorAction Stop).Path
Copy-Item $ResolvedFirstPartyLicense (Join-Path $Stage "LICENSE.txt")

@{product="MailArchive";publisher="Dietrich AI Labs";version=$Version;platform="Windows 11 x64";cleanup_policy="Move VERIFIED messages to Deleted Items only";permanent_delete=$false} |
    ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $Stage "VERSION.json")
@"
MailArchive $Version
Dietrich AI Labs

Local-first Microsoft 365 email archival utility for Windows 11 x64.
Version 1 never permanently deletes mail. Optional cleanup moves only still-verified archived messages to Deleted Items after explicit user confirmation.
User-created archive folders are not removed by uninstall.
MailArchive is proprietary freeware. See LICENSE.txt for the Dietrich AI Labs first-party license and the notices directory for third-party terms.
"@ | Set-Content -Encoding UTF8 (Join-Path $Stage "README.txt")

$ManifestPath = Join-Path $BuildRoot "package_manifest.json"
python scripts\verify_stage.py $Stage --manifest $ManifestPath
if ($LASTEXITCODE -ne 0) { throw "PACKAGE_STAGE_INSPECTION_FAILED" }

$IsccCandidates = @(
    @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }
)
if (-not $IsccCandidates) { throw "INNO_SETUP_NOT_FOUND" }
$ISCC = $IsccCandidates[0]
& $ISCC "/DMyAppVersion=$Version" "/DStageDir=$Stage" "/DOutputDir=$InstallerOut" "/DSetupIconPath=$IconPath" packaging\MailArchive.iss
if ($LASTEXITCODE -ne 0) { throw "INNO_SETUP_FAILED" }

$Installer = Get-ChildItem $InstallerOut -Filter *.exe | Select-Object -First 1
if (-not $Installer) { throw "INSTALLER_MISSING" }
$InstallerHash = (Get-FileHash -Algorithm SHA256 $Installer.FullName).Hash
$PackageZip = Join-Path $BuildRoot "MailArchive_${Version}_Runtime.zip"
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $PackageZip -Force
$PackageHash = (Get-FileHash -Algorithm SHA256 $PackageZip).Hash
$ManifestHash = (Get-FileHash -Algorithm SHA256 $ManifestPath).Hash
$SourceCommit = (git rev-parse HEAD 2>$null)
if ($LASTEXITCODE -ne 0) { $SourceCommit = "UNKNOWN" }
$SourceTree = (git rev-parse 'HEAD^{tree}' 2>$null)
if ($LASTEXITCODE -ne 0) { $SourceTree = "UNKNOWN" }
@{
    product="MailArchive"
    publisher="Dietrich AI Labs"
    version=$Version
    build_identity=$BuildIdentity
    source_commit=$SourceCommit
    source_tree=$SourceTree
    installer=$Installer.Name
    installer_sha256=$InstallerHash
    runtime_zip=(Split-Path $PackageZip -Leaf)
    runtime_zip_sha256=$PackageHash
    package_manifest=(Split-Path $ManifestPath -Leaf)
    package_manifest_sha256=$ManifestHash
    engineering_build=[bool]$EngineeringBuild
    release_candidate=$true
    supported_platform="Windows 11 x64"
    qa_release_prerequisites_satisfied=[bool]$Prerequisites.qa_release_prerequisites_satisfied
    microsoft_entra_client_configured=[bool]$Prerequisites.microsoft_entra_client_configured
    first_party_license_declared=[bool]$Prerequisites.first_party_license_declared
    first_party_license_expression=$Prerequisites.first_party_license_expression
    first_party_license_sha256=$Prerequisites.first_party_license_sha256
    permanent_delete_path_present=$false
} | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $BuildRoot "BUILD_IDENTITY.json")

Write-Host "MAILARCHIVE_WINDOWS_BUILD_PASS"
Write-Host "Installer=$($Installer.FullName)"
Write-Host "InstallerSHA256=$InstallerHash"
Write-Host "RuntimeZIP=$PackageZip"
Write-Host "RuntimeZIPSHA256=$PackageHash"
