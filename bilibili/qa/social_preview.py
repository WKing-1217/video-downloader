"""Open the locally built app with the verified social exports and isolated data."""
import json
import os
from pathlib import Path
import subprocess

root=Path(__file__).resolve().parents[1]
build=(root/'build').resolve()
reports=sorted(build.glob('social-review-*/report.json'),key=lambda p:p.stat().st_mtime,reverse=True)
work=next(p.parent.resolve() for p in reports if json.loads(p.read_text(encoding='utf-8')).get('passed'))
if not work.is_relative_to(build):
    raise RuntimeError('Preview data must stay inside the review directory')
executable=root/'dist/social-review/VideoDownloader/VideoDownloader.exe'
if not executable.is_file():
    raise RuntimeError('Build the local candidate before opening the review')
environment={**os.environ,'LOCALAPPDATA':str(work/'preferences'),'VIDEO_DOWNLOADER_OUTPUT':str(work/'media')}
environment.pop('QT_QPA_PLATFORM',None)
subprocess.Popen([str(executable)],cwd=executable.parent,env=environment,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
