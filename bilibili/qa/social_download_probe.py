"""Real source Qt queue -> worker -> MP4 -> catalogue for supplied social links."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--worker', type=Path)
args = parser.parse_args()
WORK = ROOT / 'build' / ('social-review-' + str(time.time_ns()))
WORK.mkdir(parents=True)
os.environ['LOCALAPPDATA'] = str(WORK / 'preferences')
os.environ['VIDEO_DOWNLOADER_OUTPUT'] = str(WORK / 'media')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app import DownloadWindow
from desktop_verify import prepare_fonts
from runtime_paths import configure_tools, save_settings, tool
from media_export import probe_media, full_decode
import subprocess

configure_tools()
save_settings(output=str(WORK/'media'),auto_login=False,auto_update=False,video_format='mp4')
app=QApplication([]);prepare_fonts()
window=DownloadWindow(auto_scan=False,restore_web_login=False,check_updates=False)
if args.worker:
    worker=args.worker.resolve()
    assert worker.is_file()
    window.downloads.command_factory=lambda arguments:(str(worker),arguments)
    # A fresh installation must not borrow system Node, Python or FFmpeg.
    os.environ['PATH']=str(worker.parent/'_internal/tools')+';'+os.environ.get('WINDIR','C:/Windows')+'/System32;'+os.environ.get('WINDIR','C:/Windows')
window.show()
beats=[0];timer=QTimer();timer.timeout.connect(lambda:beats.__setitem__(0,beats[0]+1));timer.start(20)
report={'passed':False,'work':str(WORK),'worker':str(args.worker) if args.worker else 'source','checks':{},'exports':[]}
urls=['https://www.instagram.com/reel/Deq-gX4SBrF/?psln=YWxhbHR5eXl5NnMw','https://youtube.com/shorts/dsbT_StiFFU?is=z0Z82UBCJvEl6MuQ']
def wait(predicate,timeout=600):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        app.processEvents();QTest.qWait(25)
        if any(t.state=='failed' for t in tasks):
            raise AssertionError([(t.platform.key,t.message) for t in tasks if t.state=='failed'])
        if predicate():return
    raise AssertionError('Social download timed out')
try:
    tasks=[window.downloads.submit(url) for url in urls]
    assert all(tasks)
    wait(lambda:all(t.state=='done' for t in tasks) and not window.downloads.busy())
    report['checks']['actual_Qt_queue_and_worker_completed']=True
    assert beats[0]>20
    report['checks']['ui_remained_responsive']=True
    for task in tasks:
        result=task.result;path=Path(result['path']);probe=probe_media(path)
        assert path.suffix=='.mp4' and path.stat().st_size>1000
        assert 'video' in {s['codec_type'] for s in probe['streams']}
        if task.platform.key=='youtube':
            assert 'audio' in {s['codec_type'] for s in probe['streams']}
        assert float(probe['format']['duration'])>0 and result['full_decode']
        full_decode(path)
        assert any(row['path']==str(path) for row in window.store.rows())
        frame=WORK/(task.platform.key+'-frame.png')
        subprocess.run([tool('ffmpeg'),'-v','error','-nostdin','-ss','1','-i',str(path),'-frames:v','1','-y',str(frame)],check=True,capture_output=True)
        report['exports'].append({**result,'sha256':hashlib.file_digest(path.open('rb'),'sha256').hexdigest(),'frame':str(frame)})
        report['checks'][task.platform.key+'_actual_mp4_streams_full_decode_catalogue']=True
    assert not list((WORK/'media').glob('*.json'))
    assert window.downloads.submit(urls[0]) is None
    report['checks']['repeat_link_is_deduplicated']=True
    window.set_page(1)
    wait(lambda:not window.library.pool.active,30)
    app.processEvents();window.grab().save(str(WORK/'library.png'))
    report['passed']=True
finally:
    timer.stop()
    report['heartbeat']=beats[0]
    report['logs']=list(window.logs)
    (WORK/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if window.downloads.process:
        window.downloads.process.kill()
        window.downloads.process.waitForFinished(10000)
    app.processEvents()
    window.install_exit=True;window.close()
    print(json.dumps({'passed':report['passed'],'checks':report['checks'],'directory':str(WORK),'exports':[r['path'] for r in report['exports']]},ensure_ascii=False),flush=True)
