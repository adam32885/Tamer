// Included in [Code] by tamer.iss (and tests/installer_env_test.iss).
//
// An older Tamer.exe that starts this installer passes on PyInstaller's bookkeeping variables (_PYI_*, _MEIPASS2).
// The installer would hand them to the Tamer.exe it opens at the end ("Open Tamer now"), which then looks for the
// old copy's unpacked files - gone, because that copy has exited - and fails with "Failed to load Python DLL".
// Removing them here fixes that even for updates started by the Tamer versions that still pass them on.

function SetEnvVarNull(lpName: String; lpValue: Cardinal): Boolean;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';
function SetEnvVarText(lpName: String; lpValue: String): Boolean;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

procedure ForgetOldTamer;
begin
  SetEnvVarNull('_PYI_ARCHIVE_FILE', 0);  // 0 = remove the variable
  SetEnvVarNull('_PYI_APPLICATION_HOME_DIR', 0);
  SetEnvVarNull('_PYI_PARENT_PROCESS_LEVEL', 0);
  SetEnvVarNull('_PYI_SPLASH_IPC', 0);
  SetEnvVarNull('_PYI_LINUX_PROCESS_NAME', 0);
  SetEnvVarNull('_MEIPASS2', 0);
  SetEnvVarText('PYINSTALLER_RESET_ENVIRONMENT', '1');  // PyInstaller 6.9+: start fresh, whatever else is left over
end;
