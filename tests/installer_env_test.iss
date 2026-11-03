; Test-only installer for test_installer_env.py: runs the same ForgetOldTamer as the real installer, then, like
; "Open Tamer now", starts a program - here cmd, which writes the environment it was given to a file.
[Setup]
AppName=TamerEnvTest
AppVersion=1
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
OutputDir={#OutDir}
OutputBaseFilename=envtest

[Run]
Filename: "{cmd}"; Parameters: "/c set > ""{param:out}"""; Flags: runhidden waituntilterminated

[Code]
#include "..\installer\clean_env.iss"

function InitializeSetup: Boolean;
begin
  ForgetOldTamer;
  Result := True;
end;
