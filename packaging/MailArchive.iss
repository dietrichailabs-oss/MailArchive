#ifndef MyAppVersion
  #define MyAppVersion "1.0.0-rc1"
#endif
#ifndef StageDir
  #define StageDir "stage"
#endif
#ifndef OutputDir
  #define OutputDir "dist-installer"
#endif
#ifndef SetupIconPath
  #define SetupIconPath "MailArchive.ico"
#endif

[Setup]
AppId={{4C7EB9B8-86E2-4CE2-82DC-704952FF0F37}
AppName=MailArchive
AppVersion={#MyAppVersion}
AppVerName=MailArchive {#MyAppVersion}
AppPublisher=Dietrich AI Labs
DefaultDirName={localappdata}\Programs\Dietrich AI Labs\MailArchive
DefaultGroupName=MailArchive
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=MailArchive_{#MyAppVersion}_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#SetupIconPath}
UninstallDisplayIcon={app}\MailArchive.exe
DisableProgramGroupPage=yes
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#StageDir}\MailArchive.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\Open Archive.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\SBOM.json"; DestDir: "{app}\notices"; Flags: ignoreversion
Source: "{#StageDir}\LICENSES.json"; DestDir: "{app}\notices"; Flags: ignoreversion
Source: "{#StageDir}\THIRD_PARTY_NOTICES.txt"; DestDir: "{app}\notices"; Flags: ignoreversion
Source: "{#StageDir}\THIRD_PARTY_LICENSES.txt"; DestDir: "{app}\notices"; Flags: ignoreversion
Source: "{#StageDir}\LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\VERSION.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\README.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\MailArchive"; Filename: "{app}\MailArchive.exe"
Name: "{autodesktop}\MailArchive"; Filename: "{app}\MailArchive.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MailArchive.exe"; Description: "Launch MailArchive"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Intentionally empty. User-created archive folders are never deleted by uninstall.
