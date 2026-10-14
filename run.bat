@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "dist\静读\静读.exe" (
    start "" "dist\静读\静读.exe" --no-top
) else if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "app.py" --no-top
) else (
    start "" pythonw "app.py" --no-top
)
