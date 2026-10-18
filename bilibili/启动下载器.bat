@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    call "安装依赖.bat"
    if errorlevel 1 exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0app.py" %*
