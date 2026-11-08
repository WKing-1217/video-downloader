@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo 请先准备项目的 Python 环境与本地候选程序。
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "qa\social_preview.py"
endlocal
