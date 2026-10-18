"""Render the real mobile QML at phone width (visual QA, not device testing)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
from pathlib import Path
import sys
from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle


class Preview(QObject):
    changed = Signal()
    link = Property(str, lambda s: "https://v.douyin.com/23O-7ujOLcw/", notify=changed)
    platform = Property(str, lambda s: "抖音", notify=changed)
    title = Property(str, lambda s: "🎂🎂🎂 #生日 #happybirthday", notify=changed)
    status = Property(str, lambda s: "导出完成 · 原图、实况和配乐已检查", notify=changed)
    details = Property(str, lambda s: "3 张图片 · 1 段实况 · 1 首配乐", notify=changed)
    logs = Property(str, lambda s: "", notify=changed)
    busy = Property(bool, lambda s: False, notify=changed)
    complete = Property(bool, lambda s: True, notify=changed)
    progress = Property(float, lambda s: 1.0, notify=changed)
    version = Property(str, lambda s: "1.0.3", notify=changed)
    updateStatus = Property(str, lambda s: "已经是最新版本", notify=changed)
    updateAvailable = Property(bool, lambda s: False, notify=changed)
    autoUpdate = Property(bool, lambda s: True, notify=changed)
    @Slot()
    def paste(self): pass
    @Slot()
    def start(self): pass
    @Slot()
    def cancel(self): pass
    @Slot()
    def login(self): pass
    @Slot()
    def openResult(self): pass
    @Slot()
    def shareResult(self): pass
    @Slot(bool)
    def checkForUpdates(self, manual=True): pass
    @Slot()
    def openUpdate(self): pass


app = QGuiApplication(sys.argv)
for name in ("msyh.ttc", "msyhbd.ttc", "seguiemj.ttf"):
    QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / name))
QQuickStyle.setStyle("Basic")
controller = Preview()
engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty("downloadApp", controller)
engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name("Main.qml").resolve())))
if not engine.rootObjects():
    raise RuntimeError("Mobile QML failed to load")
def save():
    window = engine.rootObjects()[0]
    assert window.grabWindow().save(str(Path(__file__).with_name("preview-android.png")))
    app.quit()
QTimer.singleShot(800, save)
app.exec()
