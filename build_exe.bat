@echo off
REM Builds dist\RunCheck.exe (a single file, no console window). Run from this folder.
python -m pip install -r requirements-dev.txt || goto :error
python -m PyInstaller --noconfirm --onefile --windowed --name RunCheck ^
  --add-data "runcheck\data;runcheck\data" app.py || goto :error
echo.
echo Done: dist\RunCheck.exe
exit /b 0
:error
echo Build failed.
exit /b 1
