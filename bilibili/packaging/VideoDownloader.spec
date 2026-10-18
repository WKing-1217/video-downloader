from pathlib import Path
import shutil

root = Path(SPECPATH).parent
excludes = ['PyQt5', 'PyQt6', 'PySide2', 'tkinter', 'matplotlib', 'pandas', 'scipy',
            'numpy', 'torch', 'tensorflow', 'IPython', 'jupyter', 'pytest', 'notebook']
assets = [(str(root / 'assets'), 'assets'), (str(root / 'packaging/THIRD_PARTY.txt'), '.'),
          (str(root / 'packaging/licenses'), 'licenses'), (str(root / 'version.json'), '.')]
tools = [(shutil.which(name), 'tools') for name in ('ffmpeg', 'ffprobe')]
gui = Analysis([str(root / 'app.py')], pathex=[str(root)], binaries=tools, datas=assets,
               hiddenimports=['PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineCore'],
               excludes=excludes, noarchive=False)
worker = Analysis([str(root / 'downloader.py')], pathex=[str(root)], excludes=excludes,
                  hiddenimports=['yt_dlp.extractor.lazy_extractors'], noarchive=False)
gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name='VideoDownloader',
              console=False, icon=str(root / 'assets/app.ico'), upx=False)
worker_exe = EXE(PYZ(worker.pure), worker.scripts, [], exclude_binaries=True, name='download-worker',
                 console=True, hide_console='hide-early', upx=False)
bundle = COLLECT(gui_exe, worker_exe, gui.binaries, gui.datas, worker.binaries, worker.datas,
                 strip=False, upx=False, name='VideoDownloader')
