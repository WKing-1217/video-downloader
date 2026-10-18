@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 (
        python -m venv .venv
        if errorlevel 1 goto failed
    )
)
".venv\Scripts\python.exe" -m pip install --upgrade -r requirements.txt
if errorlevel 1 goto failed
where ffmpeg >nul 2>nul
if errorlevel 1 goto ffmpeg_missing
where ffprobe >nul 2>nul
if errorlevel 1 goto ffmpeg_missing
echo 安装完成，可以双击“启动下载器.bat”。
pause
exit /b 0
:ffmpeg_missing
echo 需要安装 FFmpeg。在终端运行以下命令，然后重新打开下载器：
echo winget install --id Gyan.FFmpeg --exact
pause
exit /b 1
:failed
echo 依赖安装失败，请检查 Python 和网络后重试。
pause
exit /b 1
