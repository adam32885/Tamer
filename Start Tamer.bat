@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0tamer.py"
    exit /b
)
where py >nul 2>nul
if %errorlevel%==0 (
    start "" py -3 "%~dp0tamer.py"
    exit /b
)
echo Python was not found. Install Python 3 from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during setup.
pause
