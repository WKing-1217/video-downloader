"""Render actual Android QML at phone widths; this is layout QA, not device execution."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
from pathlib import Path
import argparse
import sys
from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle


class Preview(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._page = 0
        self._links = ["", ""]
        self._video = "mp4"
        self._image = "png"
        self._bitrate = 192
        self._auto_update = True

    def set_page(self, value):
        self._page = value
        self.changed.emit()

    def set_link(self, value):
        self._links[1 if self._page == 1 else 0] = value
        self.changed.emit()

    def set_video(self, value):
        self._video = value
        self.changed.emit()

    def set_image(self, value):
        self._image = value
        self.changed.emit()

    def set_bitrate(self, value):
        self._bitrate = value
        self.changed.emit()

    def set_auto_update(self, value):
        self._auto_update = value
        self.changed.emit()

    page = Property(int, lambda s: s._page, set_page, notify=changed)
    link = Property(str, lambda s: s._links[1 if s._page == 1 else 0], set_link, notify=changed)
    platform = Property(str, lambda s: "", notify=changed)
    title = Property(str, lambda s: "", notify=changed)
    status = Property(str, lambda s: "", notify=changed)
    details = Property(str, lambda s: "", notify=changed)
    logs = Property(str, lambda s: "", notify=changed)
    busy = Property(bool, lambda s: False, notify=changed)
    taskBusy = Property(bool, lambda s: False, notify=changed)
    hasTask = Property(bool, lambda s: False, notify=changed)
    complete = Property(bool, lambda s: False, notify=changed)
    canExtractLast = Property(bool, lambda s: False, notify=changed)
    progress = Property(float, lambda s: 0.0, notify=changed)
    videoFormat = Property(str, lambda s: s._video, set_video, notify=changed)
    imageFormat = Property(str, lambda s: s._image, set_image, notify=changed)
    audioBitrate = Property(int, lambda s: s._bitrate, set_bitrate, notify=changed)
    version = Property(str, lambda s: "1.0.5", notify=changed)
    updateStatus = Property(str, lambda s: "", notify=changed)
    updateAvailable = Property(bool, lambda s: False, notify=changed)
    autoUpdate = Property(bool, lambda s: s._auto_update, set_auto_update, notify=changed)

    @Slot()
    def paste(self): pass
    @Slot()
    def start(self): pass
    @Slot()
    def chooseLocalVideo(self): pass
    @Slot()
    def extractLastAudio(self): pass
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "bilibili/build/android-ui-review")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication(sys.argv[:1])
    for name in ("msyh.ttc", "msyhbd.ttc"):
        QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / name))
    QQuickStyle.setStyle("Basic")
    controller = Preview()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("downloadApp", controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name("Main.qml").resolve())))
    if not engine.rootObjects():
        raise RuntimeError("Mobile QML failed to load")
    window = engine.rootObjects()[0]
    shots = [(420, 860, 0, "download"), (420, 860, 1, "extract"), (420, 860, 2, "settings"),
             (360, 740, 0, "download-compact"), (360, 740, 1, "extract-compact"), (360, 740, 2, "settings-compact")]

    def capture_next():
        if not shots:
            app.quit()
            return
        width, height, page, name = shots.pop(0)
        window.setWidth(width)
        window.setHeight(height)
        controller.set_page(page)

        def save():
            path = args.output / (name + ".png")
            if not window.grabWindow().save(str(path)):
                raise RuntimeError("Could not save " + str(path))
            print(path, flush=True)
            capture_next()
        QTimer.singleShot(200, save)

    QTimer.singleShot(400, capture_next)
    app.exec()


if __name__ == "__main__":
    main()

