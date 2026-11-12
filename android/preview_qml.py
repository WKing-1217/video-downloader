"""Render actual Android QML at phone widths; this is layout QA, not device execution."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
from pathlib import Path
import json
import argparse
import sys
import PySide6
_dll_directory = os.add_dll_directory(str(Path(PySide6.__file__).parent)) if os.name == "nt" else None
from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuick import QQuickItem
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest


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
    version = Property(str, lambda s: "1.0.6 · 预览", notify=changed)
    updateStatus = Property(str, lambda s: "", notify=changed)
    updateAvailable = Property(bool, lambda s: False, notify=changed)
    autoUpdate = Property(bool, lambda s: s._auto_update, set_auto_update, notify=changed)

    libraryItems = Property("QVariantList", lambda s: [
        {"id": "example-video", "title": "示例视频", "kind": "video", "details": "视频 · 00:40", "assetCount": 1},
        {"id": "example-gallery", "title": "示例图文与实况", "kind": "gallery", "details": "3 张图片 · 1 段实况", "assetCount": 4},
    ], notify=changed)
    queuedCount = Property(int, lambda s: 0, notify=changed)
    queueStatus = Property(str, lambda s: "", notify=changed)
    libraryStatus = Property(str, lambda s: "", notify=changed)
    saveLocation = Property(str, lambda s: "下载 / 视频下载器", notify=changed)
    storageBusy = Property(bool, lambda s: False, notify=changed)

    @Slot()
    def clearQueue(self): pass
    @Slot()
    def refreshLibrary(self): pass
    @Slot(str)
    def openLibraryItem(self, item_id): pass
    @Slot(str)
    def shareLibraryItem(self, item_id): pass
    @Slot(str)
    def removeLibraryItem(self, item_id): pass
    @Slot(str)
    def extractLibraryAudio(self, item_id): pass
    @Slot()
    def chooseSaveLocation(self): pass
    @Slot()
    def resetSaveLocation(self): pass

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
    engine.warnings.connect(lambda messages: print("QML warnings:", "\n".join(m.toString() for m in messages), flush=True))
    engine.rootContext().setContextProperty("downloadApp", controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name("Main.qml").resolve())))
    if not engine.rootObjects():
        raise RuntimeError("Mobile QML failed to load")
    window = engine.rootObjects()[0]
    shots = []
    for width, height, size in [(420, 860, "default"), (360, 740, "compact"), (320, 640, "narrow"), (740, 360, "landscape")]:
        for page, label in [(0, "download"), (1, "extract"), (3, "library"), (2, "settings")]:
            shots.append((width, height, page, size + "-" + label, 0, 0))
    shots.extend([(420, 860, 0, "safearea-download", 32, 24), (360, 740, 2, "safearea-settings", 44, 32),
                  (740, 360, 0, "safearea-landscape", 24, 24), (360, 480, 0, "keyboard-download", 28, 0)])
    report = {"passed": False, "scope": "actual QML desktop rendering and synthetic safe-area margins; not Android device execution", "checks": {}, "screenshots": []}
    errors = []
    engine.warnings.connect(lambda warnings: errors.extend(str(w.toString()) for w in warnings))

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        report["checks"][name] = True

    def capture_next():
        if not shots:
            window.setHeight(860)
            window.setWidth(420)
            window.setProperty("previewKeyboardVisible", False)
            def finish_interactions():
                try:
                    navrow = window.findChild(QQuickItem, "navigationRow")
                    buttons = {int(item.objectName()[-1]): item for item in navrow.childItems() if item.objectName().startswith("navigation")}
                    for page_id in (1, 3, 2, 0):
                        item = buttons[page_id]
                        center = item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint()
                        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, center)
                        QTest.qWait(30)
                        check("tap_navigates_to_page_" + str(page_id), controller._page == page_id)
                    controller.set_page(0); controller.set_link("video share link")
                    controller.set_page(1); controller.set_link("audio share link")
                    controller.set_page(0)
                    check("page_switch_preserves_separate_links", controller.link == "video share link")
                    controller.set_page(1)
                    check("audio_link_is_preserved", controller.link == "audio share link")
                    controller.set_page(3)
                    search = window.findChild(QQuickItem, "librarySearch")
                    library = window.findChild(QQuickItem, "libraryScroll")
                    empty = window.findChild(QQuickItem, "libraryEmptyState")
                    search.setProperty("text", "图文")
                    QTest.qWait(30)
                    check("library_search_filters_real_model", library.property("resultCount") == 1 and not empty.isVisible())
                    search.setProperty("text", "不存在的作品")
                    QTest.qWait(30)
                    check("library_search_empty_state", library.property("resultCount") == 0 and empty.isVisible()
                          and empty.property("text") == "没有找到匹配作品")
                    window.grabWindow().save(str(args.output / "library-no-results.png"))
                    report["screenshots"].append("library-no-results.png")
                    clear = window.findChild(QQuickItem, "libraryClearSearch")
                    center = clear.mapToScene(QPointF(clear.width()/2, clear.height()/2)).toPoint()
                    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, center)
                    QTest.qWait(30)
                    check("library_clear_search_restores_items", library.property("resultCount") == 2 and not search.property("text"))
                    report["passed"] = True
                except Exception as error:
                    report["error"] = str(error)
                report["warnings"] = errors
                (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                app.exit(0 if report["passed"] else 1)
            QTimer.singleShot(200, finish_interactions)
            return
        width, height, page, name, safe_top, safe_bottom = shots.pop(0)
        window.setWidth(width)
        window.setHeight(height)
        window.setProperty("previewSafeTop", safe_top)
        window.setProperty("previewSafeBottom", safe_bottom)
        window.setProperty("previewKeyboardVisible", name.startswith("keyboard"))
        controller.set_page(page)

        def save():
            try:
                header = window.findChild(QQuickItem, "appHeader")
                body = window.findChild(QQuickItem, "headerBody")
                footer = window.findChild(QQuickItem, "appFooter")
                navrow = window.findChild(QQuickItem, "navigationRow")
                check(name + ":header_clears_status_bar", body.y() >= safe_top and header.height() >= safe_top + 56)
                check(name + ":footer_clears_system_navigation", footer.height() == 0 if name.startswith("keyboard") else footer.height() >= safe_bottom + navrow.height())
                scroll = window.findChild(QQuickItem, "libraryScroll" if page == 3 else "settingsScroll" if page == 2 else "transferScroll")
                check(name + ":content_is_between_bars", scroll.y() >= header.height() and scroll.y() + scroll.height() <= height - footer.height() + .1)
                buttons = sorted([item for item in navrow.childItems() if item.objectName().startswith("navigation")], key=lambda item: (0, 1, 3, 2).index(int(item.objectName()[-1])))
                check(name + ":four_destinations_exist", len(buttons) == 4)
                check(name + ":navigation_targets_equal", max(b.width() for b in buttons) - min(b.width() for b in buttons) < 1.1)
                check(name + ":navigation_targets_touchable", all(b.width() >= 64 and b.height() >= 48 for b in buttons))
                check(name + ":selected_destination_matches", all(bool(b.property("checked")) == (page_id == page) for b, page_id in zip(buttons, (0, 1, 3, 2))))
                path = args.output / (name + ".png")
                if not window.grabWindow().save(str(path)):
                    raise RuntimeError("Could not save " + str(path))
                report["screenshots"].append(path.name)
                print(path, flush=True)
                capture_next()
            except Exception as error:
                report["error"] = str(error)
                report["warnings"] = errors
                (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print("FAILED:", error, flush=True)
                app.exit(1)
        QTimer.singleShot(200, save)

    QTimer.singleShot(400, capture_next)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

