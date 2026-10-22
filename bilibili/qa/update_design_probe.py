import os,sys
from pathlib import Path
preview = '--preview' in sys.argv
if not preview:
    os.environ['QT_QPA_PLATFORM']='offscreen'
root=Path(__file__).resolve().parents[1]
os.chdir(root.parent)
sys.path.insert(0,str(root))
from PySide6.QtWidgets import QApplication
from updater import UpdatePage, UpdateReminder, TransferEstimate
from update_core import UpdateInfo
from ui_theme import stylesheet
from desktop_verify import prepare_fonts
app=QApplication([]);prepare_fonts();app.setStyleSheet(stylesheet())
import json
notes=Path('release/RELEASE_NOTES.md').read_text(encoding='utf-8')
info=UpdateInfo('2.1.1','','',303443058,notes,True)
out=Path('bilibili/build/update-polish');out.mkdir(exist_ok=True)
p=UpdatePage();p.setObjectName('pageCanvas');p.setWindowTitle('软件更新 · 设计预览');p.resize(960,660);p.notes.setMarkdown(info.notes);p.latest.setText('v2.1.1');p.transfer_panel.show();p.transfer_title.setText('正在下载 v2.1.1');p.progress.setValue(47);p.stats.setText('135.6 MB / 289.4 MB · 1.9 MB/s · 47% · 剩余 01:20');p.transfer_message.setText('正在下载更新包…');p.cancel_button.show();p.show()
for _ in range(20):app.processEvents()
p.grab().save(str(out/'page.png'))
assert p.notes.verticalScrollBar().maximum()==0
p.resize(640,440)
for _ in range(20):app.processEvents()
p.grab().save(str(out/'compact.png'))
assert p.notes.verticalScrollBar().maximum()==0
r=UpdateReminder(info);r.show()
for _ in range(20):app.processEvents()
r.grab().save(str(out/'reminder.png'))
e=TransferEstimate();e.add(0,0);last=None
for t in range(1,61):
    done=t*1000000+(200000 if t%2 else 0);e.add(t,done);speed,eta=e.read(t,100000000)
    if e.eta is not None and last is not None:assert abs(e.eta-last)<=2.01,(t,e.eta,last)
    last=e.eta
assert e.read(66,100000000)[1]=='等待网络'
e.add(67,100);assert e.eta is None
print('screenshots, single scroll, compact layout, ETA jitter/stall/reset passed',out)


if preview:
    p.resize(960,660)
    p.show()
    r.setWindowTitle('软件更新 · 设计预览')
    app.exec()
