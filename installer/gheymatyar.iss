; Inno Setup script for GheymatYar (Windows).
; Build on Windows after PyInstaller produces dist\GheymatYar\
;
;   iscc installer\gheymatyar.iss
;
; SQLite mapping data lives in %USERPROFILE%\.gheymatyar\ and is NOT
; overwritten by upgrades.

#define MyAppName "قیمت‌یار (GheymatYar)"
#define MyAppVersion "0.3.0"
#define MyAppPublisher "GheymatYar"
#define MyAppExeName "GheymatYar.exe"

[Setup]
AppId={{8F3C2A1B-9D4E-4B7A-A6C1-1234567890AB}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\GheymatYar
DefaultGroupName=GheymatYar
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=GheymatYarSetup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; PyInstaller COLLECT output
Source: "..\dist\GheymatYar\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch GheymatYar"; Flags: nowait postinstall skipifsilent

[Code]
// Mapping DB is under the user profile — never delete on uninstall/upgrade.
function InitializeUninstall(): Boolean;
begin
  Result := True;
  MsgBox('نگاشت‌های ذخیره‌شده در پوشه کاربر (.gheymatyar) باقی می‌مانند.', mbInformation, MB_OK);
end;
