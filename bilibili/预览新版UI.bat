@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "preview_ui.py"
) else (
    python "preview_ui.py"
)
endlocal
