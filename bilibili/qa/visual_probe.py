"""Render all three Qt pages and verify card geometry at the requested DPI."""
import json
import os
from pathlib import Path
import sys
import time

root = Path(__file__).resolve().parents[1]
scale = sys.argv[1] if len(sys.argv) > 1 else "1"
work = root / "build" / ("v2-visual-" + scale + "-" + str(time.time_ns()))
output = work / "video"
output.mkdir(parents=True)
os.environ.update(QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR=scale, LOCALAPPDATA=str(work / "preferences"),
                  VIDEO_DOWNLOADER_OUTPUT=str(output))
sys.path.insert(0, str(root))
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from app import DownloadWindow
from desktop_verify import prepare_fonts
app = QApplication([])
prepare_fonts()
window = DownloadWindow(auto_scan=False, restore_web_login=False, check_updates=False)
for number, title in enumerate(("手写的从前 · 完整视频", "本地预览测试片段 A", "本地预览测试片段 B")):
    source = next((root / "build/v2-live/video").glob("*.mp4")) if number == 0 else root / "build/v2-fixtures/sample.mp4"
    target = output / (title + ".mp4")
    target.hardlink_to(source)
    window.store.upsert(target, {"title": title, "duration": 294.785 if number == 0 else 6,
                                 "size": target.stat().st_size}, completed=True)
window.library.reload()
window.download_page.render_recent(window.store.rows())
window.show()
window.set_page(1)
deadline = time.monotonic() + 20
while time.monotonic() < deadline:
    app.processEvents()
    QTest.qWait(20)
    if sum(bool(row["thumb"]) for row in window.store.rows()) == 3:
        break
grid = window.library.grid
QTest.qWait(300)  # Allow deferred layout after the final thumbnail changes scrolling.
rects = [grid.visualRect(grid.model().index(i)) for i in range(3)]
window.grab().save(str(work / "layout.png"))
assert len({rect.x() for rect in rects}) == 3, (window.size(), grid.viewport().size(), grid.gridSize(), rects)
assert window.devicePixelRatioF() >= float(scale) - .02
for page in range(3):
    window.set_page(page)
    QTest.qWait(300)
    if page == 1:
        assert len({grid.visualRect(grid.model().index(i)).x() for i in range(3)}) == 3
    window.grab().save(str(work / f"page-{page}.png"))
window.resize(860, 620)
window.set_page(1)
QTest.qWait(100)
rects = [grid.visualRect(grid.model().index(i)) for i in range(3)]
assert len({rect.x() for rect in rects}) == 2, rects
assert window.library.folder_button.isVisible()
window.grab().save(str(work / "minimum-window.png"))
window.install_exit = True
window.close()
while window._jobs_running():
    app.processEvents()
    QTest.qWait(20)
report = {"passed": True, "scale": scale, "device_pixel_ratio": window.devicePixelRatioF(),
          "three_columns_at_default": True, "two_columns_at_minimum": True, "directory_footer_visible": True}
(work / "report.json").write_text(json.dumps(report), encoding="utf-8")
print(json.dumps({**report, "directory": str(work)}))
