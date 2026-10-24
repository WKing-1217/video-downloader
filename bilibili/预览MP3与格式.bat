@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "preview_ui.py" --work-dir "build\mp3-preview" --page 3 --snapshot-on-start
) else (
    python "preview_ui.py" --work-dir "build\mp3-preview" --page 3 --snapshot-on-start
)
endlocal
