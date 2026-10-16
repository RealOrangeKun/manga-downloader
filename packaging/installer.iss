; Inno Setup installer for the PyInstaller build in dist/MangaDownloader.
; Build: ISCC.exe /DAppVersion=1.2.3 packaging\installer.iss -> dist\installer\MangaDownloader-Setup-1.2.3.exe
;
; Installs per user (no admin prompt), so the app can update itself silently: it runs this with
; /VERYSILENT /update=1, which closes the app, replaces its files and opens the new version.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Never change the AppId: it's how an update finds the installed app.
AppId={{36C7F768-8CCD-453C-A53E-24898AD4D191}
AppName=Manga Downloader
AppVersion={#AppVersion}
AppVerName=Manga Downloader {#AppVersion}
AppPublisher=Youssef Tarek
AppPublisherURL=https://github.com/RealOrangeKun/manga-downloader
AppUpdatesURL=https://github.com/RealOrangeKun/manga-downloader/releases
DefaultDirName={localappdata}\Programs\Manga Downloader
DefaultGroupName=Manga Downloader
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=MangaDownloader-Setup-{#AppVersion}
SetupIconFile=..\build\icon.ico
UninstallDisplayIcon={app}\MangaDownloader.exe
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

[Files]
Source: "..\dist\MangaDownloader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Manga Downloader"; Filename: "{app}\MangaDownloader.exe"
Name: "{autodesktop}\Manga Downloader"; Filename: "{app}\MangaDownloader.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MangaDownloader.exe"; Description: "{cm:LaunchProgram,Manga Downloader}"; Flags: nowait postinstall skipifsilent
; After a self-update the installer runs silently, so open the app again here.
Filename: "{app}\MangaDownloader.exe"; Flags: nowait; Check: IsUpdate

[Code]
function IsUpdate: Boolean;
begin
  Result := ExpandConstant('{param:update|0}') = '1';
end;
