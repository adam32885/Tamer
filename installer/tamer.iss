; Tamer installer (Inno Setup 6). Build it with build_installer.bat, which passes the version from tamer.py.
; Installs for the current user only (no admin prompt) into AppData\Local\Programs\Tamer. Tamer keeps its
; settings, logs, backups and default server folder next to Tamer.exe, so that folder has to stay writable.

#ifndef AppVersion
  #error Run build_installer.bat (it passes /DAppVersion=... from tamer.py)
#endif

[Setup]
; Never change AppId: it's how a newer installer finds and updates an older install
AppId={{8E4C5B1A-3F2D-4C9A-B6E7-5D1F0A2C9B43}
AppName=Tamer
AppVersion={#AppVersion}
AppVerName=Tamer {#AppVersion}
AppPublisher=InternalDark
AppComments=Tame your server - ARK: Survival Ascended dedicated server manager
DefaultDirName={localappdata}\Programs\Tamer
DefaultGroupName=Tamer
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
UsedUserAreasWarning=no
OutputDir=Output
OutputBaseFilename=Tamer-Setup-{#AppVersion}
SetupIconFile=..\tamer.ico
UninstallDisplayIcon={app}\Tamer.exe
UninstallDisplayName=Tamer
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
; Close a running Tamer before replacing it. ARK servers are separate programs and keep running.
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked
Name: "startup"; Description: "&Start Tamer when I sign in to Windows"; Flags: unchecked

[Files]
Source: "..\dist\Tamer.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Tamer"; Filename: "{app}\Tamer.exe"; WorkingDir: "{app}"
Name: "{group}\Uninstall Tamer"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Tamer"; Filename: "{app}\Tamer.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Tamer.exe"; Description: "Open Tamer now"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
#include "clean_env.iss"

function InitializeSetup: Boolean;
begin
  ForgetOldTamer;  // before anything starts Tamer.exe again (see clean_env.iss)
  Result := True;
end;

// The same startup entry Tamer's own "Start with Windows" setting writes (see set_start_with_windows in
// tamer.py), so the tick box here and the one inside Tamer stay in agreement.
function StartupBat: String;
begin
  Result := ExpandConstant('{userstartup}\Tamer.bat');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('startup') then
    SaveStringToFile(StartupBat, '@echo off' + #13#10 + 'cd /d "' + ExpandConstant('{app}') + '"' + #13#10 +
                     'start "" "' + ExpandConstant('{app}\Tamer.exe') + '"' + #13#10, False);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Bat: AnsiString;
begin
  if CurUninstallStep = usUninstall then
  begin
    // only remove the startup entry if it starts this copy of Tamer
    if LoadStringFromFile(StartupBat, Bat) and (Pos(Uppercase(ExpandConstant('{app}')), Uppercase(String(Bat))) > 0) then
      DeleteFile(StartupBat);
  end;
  if (CurUninstallStep = usPostUninstall) and DirExists(ExpandConstant('{app}')) and not UninstallSilent then
    MsgBox('Tamer is uninstalled.' + #13#10#13#10 +
           'Your settings, logs, backups and any servers stored there were kept, in:' + #13#10 +
           ExpandConstant('{app}') + #13#10#13#10 +
           'Delete that folder yourself if you don''t need them any more. Servers you put in other folders ' +
           'are where you left them.', mbInformation, MB_OK);
end;
