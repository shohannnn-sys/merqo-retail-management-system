; Inno Setup 6 script for Retvia.
;
;   iscc /DAppVersion=0.1.0 /DSourceDir=..\dist\Retvia packaging\installer.iss
;
; Design rules enforced here:
;   * Per-user install by default (no admin prompt for a single-shop PC), with an
;     optional all-users install into Program Files.
;   * Business data lives in %LOCALAPPDATA%\Retvia and is NEVER touched by the
;     installer or the uninstaller.
;   * No bundled runtime download: PyInstaller already produced a self-contained
;     folder, so the installer works with no internet connection.

#define AppName "Retvia"
#define AppPublisher "MERQO"
#define AppURL "https://github.com/shohannnn-sys/merqo-retail-management-system"
#define AppSupportEmail "merqoonline@gmail.com"
#define AppExeName "Retvia.exe"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\Retvia"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\installer"
#endif

[Setup]
AppId={{8F3C1D62-5B47-4E19-9C0A-7D2E5A6B4C11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
AppContact={#AppSupportEmail}
AppCopyright=Copyright (c) 2026 MERQO — Founder: Shohan Khan
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#OutputDir}
OutputBaseFilename=Retvia-Setup-{#AppVersion}
SetupIconFile=..\retvia\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Retail Management System Setup
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
LicenseFile=..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
CreateDesktopIcon=Create a desktop shortcut
LaunchAfterInstall=Launch Retvia now
DataPreserved=Your business data in %LOCALAPPDATA%\Retvia is kept.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\docs\USER_GUIDE_BN.md"; DestDir: "{app}\docs"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\docs\USER_GUIDE_BN.html"; DestDir: "{app}\docs"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Dirs]
; Per-user data folders are created by the app itself on first run. Declaring
; them here with uninsneveruninstall makes the intent explicit and guarantees
; the uninstaller never removes business data.
Name: "{localappdata}\Retvia"; Flags: uninsneveruninstall
Name: "{localappdata}\Retvia\data"; Flags: uninsneveruninstall
Name: "{localappdata}\Retvia\backups"; Flags: uninsneveruninstall
Name: "{localappdata}\Retvia\logs"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{group}\User Guide (বাংলা)"; Filename: "{app}\docs\USER_GUIDE_BN.html"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon; IconFilename: "{app}\{#AppExeName}"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchAfterInstall}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only program files. Nothing under {localappdata}\Retvia is ever listed here.
Type: filesandordirs; Name: "{app}\_internal"

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    MsgBox('Retvia has been removed.' + #13#10 + #13#10 +
           'Your business data, backups and logs were kept in:' + #13#10 +
           ExpandConstant('{localappdata}\Retvia') + #13#10 + #13#10 +
           'Delete that folder manually only if you are sure you no longer need it.',
           mbInformation, MB_OK);
  end;
end;
