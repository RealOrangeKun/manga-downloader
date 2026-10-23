; Inno Setup installer for the PyInstaller build in dist/Nyanga.
; Build: ISCC.exe /DAppVersion=1.2.3 packaging\installer.iss -> dist\installer\Nyanga-Setup-1.2.3.exe
;
; Installs per user (no admin prompt), so the app can update itself silently: it runs this with
; /VERYSILENT /update=1, which closes the app, replaces its files and opens the new version.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Never change the AppId: it's how an update finds the installed app.
AppId={{36C7F768-8CCD-453C-A53E-24898AD4D191}
AppName=Nyanga
AppVersion={#AppVersion}
AppVerName=Nyanga {#AppVersion}
AppPublisher=Youssef Tarek
AppPublisherURL=https://github.com/nyanga-app/nyanga-app
AppUpdatesURL=https://github.com/nyanga-app/nyanga-app/releases
DefaultDirName={localappdata}\Programs\Nyanga
DefaultGroupName=Nyanga
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=Nyanga-Setup-{#AppVersion}
SetupIconFile=..\build\icon.ico
UninstallDisplayIcon={app}\Nyanga.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no

[Tasks]
Name: desktopicon; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Old libraries go first so nothing from the previous version is left behind.
Type: filesandordirs; Name: "{app}\_internal"

[UninstallDelete]
; Updates can add files the installer never saw (only the changed files get downloaded), so
; uninstalling clears the whole folder.
Type: filesandordirs; Name: "{app}"

[Files]
Source: "..\dist\Nyanga\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Nyanga"; Filename: "{app}\Nyanga.exe"
Name: "{autodesktop}\Nyanga"; Filename: "{app}\Nyanga.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Nyanga.exe"; Description: "{cm:LaunchProgram,Nyanga}"; Flags: nowait postinstall skipifsilent
; After a self-update the installer runs silently, so open the app again here.
Filename: "{app}\Nyanga.exe"; Flags: nowait; Check: IsUpdate

[Code]
function IsUpdate: Boolean;
begin
  Result := ExpandConstant('{param:update|0}') = '1';
end;
