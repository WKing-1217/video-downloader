import json, os, sys, time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
work=root/'build'/'v2-player-qa';work.mkdir(exist_ok=True)
os.environ['QT_QPA_PLATFORM']='offscreen'
sys.path.insert(0,str(root))
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from media_player import PlayerDialog
from ui_theme import stylesheet
from desktop_verify import prepare_fonts
app=QApplication([]);prepare_fonts();app.setStyleSheet(stylesheet())
dialog=PlayerDialog(root/'build/v2-fixtures/sample.mp4','本地播放检查')
frames=[]
def frame(value):
    if value.isValid():
        frames.append(1)
        if len(frames)==2:value.toImage().save(str(work/'decoded-frame.png'))
dialog.video.videoSink().videoFrameChanged.connect(frame)
dialog.show()
deadline=time.monotonic()+12
while len(frames)<3 and time.monotonic()<deadline:
    app.processEvents();QTest.qWait(20)
assert len(frames)>=3,(dialog.player.errorString(),dialog.player.mediaStatus(),len(frames))
dialog.player.pause();QTest.qWait(80)
assert dialog.player.playbackState()==QMediaPlayer.PausedState
dialog.player.setPosition(3000);QTest.qWait(200)
assert abs(dialog.player.position()-3000)<500
dialog.volume.setValue(30)
assert abs(dialog.audio.volume()-0.3)<0.01
dialog.toggle_fullscreen();QTest.qWait(100);assert dialog.isFullScreen()
QTest.keyClick(dialog,Qt.Key_Escape);QTest.qWait(100);assert not dialog.isFullScreen()
dialog.grab().save(str(work/'player.png'))
dialog.close();QTest.qWait(80)
error=PlayerDialog(work/'missing.mp4','错误恢复检查');error.show();QTest.qWait(80)
assert error.error_label.isVisible() and not error.external.isEnabled()
error.close();QTest.qWait(50)
proof={'passed':True,'decoded_video_frames':len(frames),'pause_seek_volume_fullscreen':True,'missing_file_feedback':True}
(work/'report.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
print(json.dumps(proof))
