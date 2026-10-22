@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "preview_ui.py" --work-dir "build\storage-preview" --page 1 --expanded
) else (
    python "preview_ui.py" --work-dir "build\storage-preview" --page 1 --expanded
)
endlocal
