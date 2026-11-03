@echo off
REM Builds dist\Tamer.exe, then the installer installer\Output\Tamer-Setup-<version>.exe
REM Needs PyInstaller (pip install pyinstaller) and Inno Setup 6 (winget install JRSoftware.InnoSetup)
cd /d "%~dp0"
REM the version from the line  APP_VERSION = "1.2.3"  in tamer.py
set VER=
for /f "tokens=2 delims==" %%v in ('findstr /b /c:"APP_VERSION = " tamer.py') do set VER=%%v
if not defined VER goto :fail
set VER=%VER: =%
set VER=%VER:"=%
set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" (
    echo Inno Setup 6 isn't installed. Run: winget install JRSoftware.InnoSetup
    goto :fail
)
python -m PyInstaller --noconfirm --onefile --windowed --name Tamer --icon tamer.ico --add-data "tamer.ico;." --add-data "tamer.png;." tamer.py || goto :fail
"%ISCC%" /Q /DAppVersion=%VER% installer\tamer.iss || goto :fail
echo.
echo Done: installer\Output\Tamer-Setup-%VER%.exe
if not "%1"=="nopause" pause
exit /b 0
:fail
echo Build failed.
if not "%1"=="nopause" pause
exit /b 1
