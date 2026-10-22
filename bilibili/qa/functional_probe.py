"""Real Qt paste/events/process/catalogue integration with a controlled worker."""
import json, os, shutil, sys, time
from pathlib import Path
from unittest.mock import patch
root = Path(__file__).resolve().parents[1]
work = root / 'build' / ('v2-functional-' + str(time.time_ns()))
work.mkdir(exist_ok=True)
os.environ['LOCALAPPDATA'] = str(work / 'preferences')
os.environ['VIDEO_DOWNLOADER_OUTPUT'] = str(work / 'videos')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(root))
from PySide6.QtCore import QTimer, Qt, QPoint
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QMessageBox
from app import DownloadWindow
from desktop_verify import prepare_fonts
from media_library import LibraryStore
from ui_theme import icon
video = work / 'videos'; video.mkdir(exist_ok=True)
sample = root / 'build/v2-fixtures/sample.mp4'
history = video / '原有历史视频.mp4'
shutil.copy2(sample, history)
worker = work / 'controlled_worker.py'
worker.write_text('''import json,os,sys,time,shutil
from pathlib import Path
sys.path.insert(0,'''+repr(str(root))+''')
from downloader import verify_media
def emit(kind,**data):print(json.dumps(dict(event=kind,**data),ensure_ascii=False),flush=True)
out=Path(os.environ['VIDEO_DOWNLOADER_OUTPUT']);out.mkdir(exist_ok=True)
sample=Path('''+repr(str(sample))+''')
key=sys.argv[1].split('/video/')[-1].split('?')[0]
destination=out/('测试下载 ['+key+'].mp4')
emit('metadata',title='测试下载 '+key,duration=6)
total=sample.stat().st_size;done=0
with sample.open('rb') as src,destination.open('wb') as dst:
 while data:=src.read(65536):
  dst.write(data);done+=len(data);emit('progress',downloaded=done,total=total,speed=655360,eta=(total-done)/655360);time.sleep(.05)
result=verify_media(destination,6);result.update(title='测试下载 '+key,platform='bilibili')
destination.with_suffix('.mp4.info.json').write_text(json.dumps(result),encoding='utf-8')
emit('complete',**result)
''',encoding='utf-8')
app=QApplication([]);prepare_fonts()
store=LibraryStore(work/'preferences/LocalVideoDownloader/test-library.sqlite3')
window=DownloadWindow(auto_scan=False,restore_web_login=False,check_updates=False,store=store,
                      command_factory=lambda args:(sys.executable,[str(worker),*args]))
window.show()
proof={'passed':False,'controlled_worker_fixture':True,'checks':{}}
beats=[0];timer=QTimer();timer.timeout.connect(lambda:beats.__setitem__(0,beats[0]+1));timer.start(10)
def wait_until(condition,seconds=12):
 deadline=time.monotonic()+seconds
 while time.monotonic()<deadline:
  app.processEvents();QTest.qWait(15)
  if condition():return
 raise AssertionError('Timed out')
def check(name,condition):
 assert condition,name
 proof['checks'][name]=True
try:
 check('default_download_page',window.pages.currentIndex()==0 and len(window.navigation)==3)
 check('vector_navigation_and_settings_icons',not icon('settings').pixmap(20,20).isNull())
 app.clipboard().setText('https://www.bilibili.com/video/BV1yUFPzKEC7')
 QTest.qWait(50);check('does_not_watch_system_clipboard',not window.downloads.busy())
 window.url.setFocus();QTest.keyClicks(window.url,'https://www.bilibili.com/vid')
 QTest.qWait(30);check('manual_partial_typing_does_not_download',not window.downloads.busy())
 app.clipboard().setText('not a video link');QTest.mouseClick(window.download_page.paste,Qt.LeftButton)
 check('paste_button_fills_without_submitting',window.url.text()=='not a video link' and not window.downloads.busy() and not window.download_page.input_message.isVisible())
 QTest.mouseClick(window.download_page.submit,Qt.LeftButton)
 check('invalid_submit_rejected',not window.downloads.busy() and window.download_page.input_message.isVisible())
 completed=[];window.downloads.completed.connect(completed.append)
 app.clipboard().setText('https://www.bilibili.com/video/BV1yUFPzKEC7')
 QTest.keyClick(window.url,Qt.Key_V,Qt.ControlModifier)
 check('keyboard_paste_waits_for_submit',not window.downloads.busy())
 QTest.mouseClick(window.download_page.submit,Qt.LeftButton)
 QTest.mouseClick(window.download_page.submit,Qt.LeftButton)
 check('duplicate_submit_has_one_pending_key',len(window.downloads.pending_keys)==1)
 wait_until(lambda:len(completed)==1 and not window.downloads.busy())
 check('submit_downloads_and_catalogues',bool(completed[0].get('library_id')) and len(store.rows())>=1)
 check('ui_responsive_during_download',beats[0]>=25)
 window.library.refresh();wait_until(lambda:not window.library.scanning)
 check('old_video_imported',any(item['path']==str(history) for item in store.rows()))
 window.set_page(1);QTest.qWait(100)
 wait_until(lambda:any(item.get('thumb') for item in window.library.model.all_rows),20)
 check('real_thumbnail_generated',any(Path(item['thumb']).is_file() for item in store.rows() if item['thumb']))
 window.library.search.setText('原有');check('search_title',len(window.library.model.rows)==1)
 window.library.search.clear();window.library.sort.setCurrentIndex(1)
 check('download_time_sort',window.library.model.rows[0]['completed']<=window.library.model.rows[-1]['completed'])
 with patch('library_page.QDesktopServices.openUrl',return_value=True) as opened:
  window.library.open_folder();check('open_folder_uses_native_directory_url',opened.call_args.args[0].isLocalFile())
 new=work/'new-videos';window.choose_output(str(new))
 check('changing_directory_preserves_history',history.exists() and str(video.resolve()) in store.roots() and str(new.resolve()) in store.roots())
 item=next(item for item in store.rows() if item['path']==str(history))
 window.open_media(item);QTest.qWait(300)
 check('card_opens_internal_player',window.player_dialog.player.source().isLocalFile())
 window.player_dialog.close();QTest.qWait(100);window.player_dialog=None
 window.library.model.filter('',False)
 window.resize(860,620);QTest.qWait(100)
 check('minimum_window_navigation_and_footer_fit',window.pages.width()>500 and window.library.folder_button.isVisible())
 window.grab().save(str(work/'library.png'))
 window.library.remove_record(item);store.scan()
 check('remove_record_preserves_file_and_stays_hidden',history.exists() and not any(row['id']==item['id'] for row in store.rows()))
 record=next(row for row in store.rows() if row['kind']=='video')
 target=Path(record['path'])
 with patch.object(QMessageBox,'exec',return_value=QMessageBox.Cancel):window.library.delete_file(record)
 check('cancel_file_delete_preserves_file',target.exists())
 with patch.object(QMessageBox,'exec',return_value=QMessageBox.Yes):window.library.delete_file(record)
 check('confirmed_file_delete_removes_file',not target.exists())
 window.set_page(0)
 window.downloads.output=video
 # Right-click paste goes through the menu action, not textChanged.
 app.clipboard().setText('https://www.bilibili.com/video/BV1fyeh6GEkL')
 def menu_paste():
  menu=app.activePopupWidget()
  if menu:
   next(action for action in menu.actions() if action.objectName()=='pasteLink').trigger();menu.close()
 QTimer.singleShot(30,menu_paste)
 event=QContextMenuEvent(QContextMenuEvent.Mouse,QPoint(20,20),window.url.mapToGlobal(QPoint(20,20)))
 app.sendEvent(window.url,event)
 check('context_menu_paste_waits_for_submit',not window.downloads.busy())
 QTest.keyClick(window.url,Qt.Key_Return)
 wait_until(lambda:len(completed)==2 and not window.downloads.busy())
 check('context_paste_then_enter_downloads',len(completed)==2)
 proof['passed']=True
finally:
 timer.stop()
 window.closing=True;window.close()
 deadline=time.monotonic()+20
 while window._jobs_running() and time.monotonic()<deadline:app.processEvents();QTest.qWait(20)
 app.processEvents()
 (work/'report.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(proof),flush=True)
assert proof['passed']
