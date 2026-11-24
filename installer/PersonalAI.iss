#define MyAppName "PersonalAI"
#define MyAppVersion "4.2.0"
[Setup]
AppId={{F6C986D1-7D72-4AA7-9AAA-671A7F4FB053}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\PersonalAI
DefaultGroupName=PersonalAI
OutputDir=..\output
OutputBaseFilename=PersonalAI-Setup-4.2.0
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\PersonalAI.exe
WizardStyle=modern
[Files]
Source: "..\installer-dist\PersonalAI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{autoprograms}\PersonalAI"; Filename: "{app}\PersonalAI.exe"
Name: "{autodesktop}\PersonalAI"; Filename: "{app}\PersonalAI.exe"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно:"
[Run]
Filename: "{app}\PersonalAI.exe"; Description: "Запустить PersonalAI"; Flags: nowait postinstall skipifsilent
