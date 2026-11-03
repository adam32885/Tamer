@echo off
REM Builds a single-file Tamer.exe with its icon (optional - tamer.py runs fine on its own)
cd /d "%~dp0"
python -m pip install --upgrade pyinstaller || goto :fail
python -m PyInstaller --noconfirm --onefile --windowed --name Tamer --icon tamer.ico --add-data "tamer.ico;." --add-data "tamer.png;." tamer.py || goto :fail
echo.
echo Done: dist\Tamer.exe
echo Put the exe in its own folder - it keeps its data next to itself.
pause
exit /b
:fail
echo Build failed.
pause
