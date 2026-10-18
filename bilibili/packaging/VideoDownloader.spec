from pathlib import Path
import json
import shutil
import PySide6

root = Path(SPECPATH).parent
def keep_runtime(entry):
    # Windows 10/11 provide the ICU and UCRT APIs used by Qt. Do not bundle
    # incompatible same-name DLLs found on the build machine's tool PATH.
    name = Path(entry[0]).name.lower()
    return not (name in {'icuuc.dll', 'ucrtbase.dll'} or name.startswith('api-ms-win-')
                or (name.startswith('icudt') and name.endswith('.dll')))

excludes = ['PyQt5', 'PyQt6', 'PySide2', 'tkinter', 'matplotlib', 'pandas', 'scipy',
            'numpy', 'torch', 'tensorflow', 'IPython', 'jupyter', 'pytest', 'notebook']
assets = [(str(root / 'assets'), 'assets'), (str(root / 'packaging/THIRD_PARTY.txt'), '.'),
          (str(root / 'packaging/licenses'), 'licenses'), (str(root / 'version.json'), '.')]
tools = [(shutil.which(name), 'tools') for name in ('ffmpeg', 'ffprobe')]
codecs = [(str(path), 'PySide6') for pattern in ('avutil-*.dll', 'swresample-*.dll', 'swscale-*.dll', 'avcodec-*.dll', 'avformat-*.dll')
          for path in Path(PySide6.__file__).parent.glob(pattern)]
agent = Analysis([str(root / 'update_agent.py')], pathex=[str(root)], excludes=excludes + ['PySide6'], noarchive=False)
agent.binaries = [entry for entry in agent.binaries if keep_runtime(entry)]
agent_exe = EXE(PYZ(agent.pure), agent.scripts, agent.binaries, agent.datas, [], name='update-helper',
                console=False, icon=str(root / 'assets/app.ico'), upx=False)
gui = Analysis([str(root / 'app.py')], pathex=[str(root)], binaries=tools + codecs, datas=assets,
               hiddenimports=['PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineCore'],
               excludes=excludes, noarchive=False)
worker = Analysis([str(root / 'downloader.py')], pathex=[str(root)], excludes=excludes,
                  hiddenimports=['yt_dlp.extractor.lazy_extractors'], noarchive=False)
gui.binaries = [entry for entry in gui.binaries if keep_runtime(entry)]
worker.binaries = [entry for entry in worker.binaries if keep_runtime(entry)]
gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name='VideoDownloader',
              console=False, icon=str(root / 'assets/app.ico'), upx=False)
worker_exe = EXE(PYZ(worker.pure), worker.scripts, [], exclude_binaries=True, name='download-worker',
                 console=True, hide_console='hide-early', upx=False)
bundle = COLLECT(gui_exe, worker_exe, gui.binaries, gui.datas, worker.binaries, worker.datas,
                 strip=False, upx=False, name='VideoDownloader')
destination = Path(bundle.name)
shutil.copy2(agent_exe.name, destination / 'update-helper.exe')
files = sorted(str(path.relative_to(destination)).replace('\\', '/') for path in destination.rglob('*') if path.is_file())
files.append('install-manifest.json')
(destination / 'install-manifest.json').write_text(json.dumps({
    'product': 'LocalVideoDownloader', 'version': json.loads((root / 'version.json').read_text())['version'],
    'files': files}, ensure_ascii=False, indent=2), encoding='utf-8')
