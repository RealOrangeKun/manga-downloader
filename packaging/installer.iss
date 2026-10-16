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
AppPublisherURL=https://github.com/RealOrangeKun/nyanga
AppUpdatesURL=https://github.com/RealOrangeKun/nyanga/releases
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
var
  ImportPage: TInputOptionWizardPage;
  FolderPage: TInputDirWizardPage;

function IsUpdate: Boolean;
begin
  Result := ExpandConstant('{param:update|0}') = '1';
end;

{ Where the installed app keeps its settings and library (paths.DATA in the app). }
function DataDir: String;
begin
  Result := ExpandConstant('{userappdata}\Nyanga');
end;

function OldFolder: String;
begin
  Result := RemoveBackslashUnlessRoot(FolderPage.Values[0]);
end;

{ Two optional pages after the tasks: "did you run it from Python before?" and, if so, where. }
procedure InitializeWizard;
begin
  ImportPage := CreateInputOptionPage(wpSelectTasks,
    'Bring your old settings', 'Did you use Nyanga with Python before?',
    'If you ran nyanga.py before, your settings and library (download history and covers) can come along.',
    False, False);
  ImportPage.Add('Yes, import them from my old copy');
  FolderPage := CreateInputDirPage(ImportPage.ID,
    'Where is the old copy?', 'Pick the folder that has nyanga.py in it',
    'Its settings.json and library folder are copied over and replace any the app already has. ' +
    'The old folder isn''t changed.',
    False, '');
  FolderPage.Add('');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = FolderPage.ID) and not ImportPage.Values[0];
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = FolderPage.ID) and not FileExists(OldFolder + '\settings.json')
     and not FileExists(OldFolder + '\library\history.json') then
  begin
    MsgBox('There''s no settings.json or library folder in there. Pick the folder with nyanga.py ' +
           'in it, or go back and untick the import.', mbError, MB_OK);
    Result := False;
  end;
end;

procedure CopyTree(const Source, Dest: String);
var
  Rec: TFindRec;
begin
  ForceDirectories(Dest);
  if FindFirst(Source + '\*', Rec) then
  try
    repeat
      if (Rec.Name <> '.') and (Rec.Name <> '..') then
        if (Rec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
          CopyTree(Source + '\' + Rec.Name, Dest + '\' + Rec.Name)
        else
          FileCopy(Source + '\' + Rec.Name, Dest + '\' + Rec.Name, False);
    until not FindNext(Rec);
  finally
    FindClose(Rec);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and ImportPage.Values[0] then
  begin
    ForceDirectories(DataDir);
    if FileExists(OldFolder + '\settings.json') then
      FileCopy(OldFolder + '\settings.json', DataDir + '\settings.json', False);
    if DirExists(OldFolder + '\library') then
      CopyTree(OldFolder + '\library', DataDir + '\library');
  end;
end;
