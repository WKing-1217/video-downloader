"""Real Qt events for directory changes, file deletion and long sidebar titles."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
work = root / "build/storage-review" / ("qt-" + str(time.time_ns()))
output = work / "旧视频"
output.mkdir(parents=True)
os.environ["LOCALAPPDATA"] = str(work / "preferences")
os.environ.pop("VIDEO_DOWNLOADER_OUTPUT", None)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(root))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from app import DownloadWindow
from desktop_verify import prepare_fonts
from library_page import MediaDelegate, MediaModel
from media_library import LibraryStore, gallery_assets
from runtime_paths import read_settings, save_settings
from ui_theme import RAIL

app = QApplication([])
prepare_fonts()
save_settings(output=str(output), auto_update=False, auto_login=False)
store = LibraryStore()
sample = root / "build/v2-fixtures/sample.mp4"
ids = []
for number in range(2):
    path = output / f"视频 {number + 1}.mp4"
    shutil.copy2(sample, path)
    content = {"title": "这是一条超出侧栏宽度的真实作品长标题，边缘渐隐并自动滚动显示完整内容 " + str(number),
               "duration": 6, "size": path.stat().st_size}
    ids.append(store.upsert(path, content, completed=True))
large = output / ".downloads/fixture.part"
large.parent.mkdir()
large.write_bytes(b"migration fixture " * (1024 * 1024))
folder = output / "图文作品"
folder.mkdir()
assets = []
for number in range(2):
    path = folder / f"{number:03d}.png"
    image = QImage(640, 420, QImage.Format_RGB32)
    image.fill(QColor("#d6d6d6" if number else "#444444"))
    image.save(str(path))
    assets.append({"kind": "image", "path": str(path)})
metadata = {"title": "图文作品", "content_type": "gallery", "assets": assets,
            "size": sum(Path(asset["path"]).stat().st_size for asset in assets)}
(folder / "作品信息.json").write_text(json.dumps(metadata), encoding="utf-8")
album_id = store.upsert(folder, metadata, completed=True)
window = DownloadWindow(auto_scan=False, restore_web_login=False, check_updates=False, store=store)
window.show()
report = {"passed": False, "checks": {}, "directory": str(work), "controlled_copy_delay": True}
beats = [0]
timer = QTimer()
timer.setInterval(10)
timer.timeout.connect(lambda: beats.__setitem__(0, beats[0] + 1))
timer.start()

def wait(condition, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(15)
        if condition():
            return
    raise AssertionError("Qt storage review timed out")

def check(name, condition):
    assert condition, name
    report["checks"][name] = True

def shot(name, widget=window):
    assert widget.grab().save(str(work / (name + ".png")))

try:
    wait(lambda: not window.library.scanning and not window.library.pool.active)
    QTest.mouseClick(window.menu_button, Qt.LeftButton)
    QTest.qWait(100)
    recent = window.icon_rail.recent
    check("overflow_titles_start_animation", recent.animation.isActive())
    shot("sidebar-fade-start")
    QTest.qWait(2100)
    width = recent.fontMetrics().horizontalAdvance(store.get(ids[0])["title"])
    check("overflow_titles_scroll_automatically", recent.title_offset(width, recent.viewport().width() - 24) > 20)
    shot("sidebar-fade-scrolling")
    available = recent.viewport().width() - 24
    period = width + RAIL["title_gap"]
    class ReviewClock:
        elapsed_ms = 0
        def elapsed(self):
            return self.elapsed_ms
    clock = ReviewClock()
    with patch.object(recent, "clock", clock):
        values = []
        for distance in (20, width - available + 20, period - 20):
            clock.elapsed_ms = RAIL["title_pause_ms"] + distance * 1000 / RAIL["title_speed"]
            values.append(recent.title_offset(width, available))
        check("long_title_keeps_moving_left_past_its_end", values[0] < values[1] < values[2] and values[1] > width - available)
        shot("sidebar-single-direction-before-loop")
        clock.elapsed_ms += 40 * 1000 / RAIL["title_speed"]
        next_offset = recent.title_offset(width, available)
        check("long_title_loops_without_reverse_motion", abs(next_offset + period - values[-1] - 40) < 1)
        check("short_sidebar_titles_remain_still", recent.title_offset(30, available) == 0)
        shot("sidebar-single-direction-next-loop")
    window.splitter.moveSplitter(390, 1)
    QTest.qWait(80)
    check("sidebar_can_resize_and_remembers_width", window.icon_rail.width() >= 380 and read_settings()["sidebar_width"] >= 380)
    window.resize(860, 620)
    QTest.qWait(100)
    check("sidebar_adapts_to_narrow_window", window.body_canvas.width() >= RAIL["content_min"] and window.icon_rail.width() < 310)
    window.resize(1120, 780)
    window.splitter.moveSplitter(RAIL["expanded_width"], 1)
    window.set_page(1)
    wait(lambda: not window.library.pool.active)
    window.open_settings()
    shot("settings-download-location", window.settings_dialog)
    target = work / "新视频"
    window.last_result = {"path": store.get(ids[0])["path"]}
    original_run = window.storage.service.run
    def delayed_run(destination, progress):
        def delayed_progress(*args):
            progress(*args)
            if args[0] == "copying":
                time.sleep(.018)
        return original_run(destination, delayed_progress)
    window.storage.service.run = delayed_run
    before = beats[0]
    with patch.object(QFileDialog, "getExistingDirectory", return_value=str(target)):
        QTest.mouseClick(window.settings_dialog.location_bar.choose_button, Qt.LeftButton)
    check("settings_change_starts_migration", window.storage.running and window.downloads.output_locked)
    check("download_submission_is_blocked_during_move", window.submit_link("https://www.bilibili.com/video/BV1yUFPzKEC7") is None)
    wait(lambda: window.storage.running and window.storage.dialog.status.text().startswith("正在复制"))
    check("migration_shows_actual_byte_progress", "/" in window.storage.dialog.status.text())
    shot("migration-progress", window.storage.dialog)
    wait(lambda: not window.storage.running)
    check("migration_keeps_ui_responsive", beats[0] - before >= 10)
    check("migration_updates_all_app_locations", window.output == target and window.downloads.output == target
          and window.library.output == target and read_settings()["output"] == str(target))
    check("migration_cleans_old_directory", not output.exists())
    check("migration_updates_last_result_and_unlocks_downloads", Path(window.last_result["path"]).is_file() and not window.downloads.output_locked)
    check("migration_keeps_ids_and_album_files", all(Path(store.get(identifier)["path"]).exists() for identifier in [*ids, album_id]))
    check("migration_updates_watchers", str(output) not in window.library.watcher.directories())
    shot("migration-complete", window.storage.dialog)
    window.storage.dialog.close()
    window.settings_dialog.close()
    wait(lambda: not window.library.pool.active)
    # Card deletion is a different hit target from play/open.
    window.library.reload()
    row = next(index for index, item in enumerate(window.library.model.rows) if item["id"] == ids[0])
    index = window.library.model.index(row)
    window.library.grid.scrollTo(index)
    QTest.qWait(60)
    point = MediaDelegate.delete_rect(window.library.grid.visualRect(index)).center()
    QTest.mouseMove(window.library.grid.viewport(), point)
    shot("library-delete-action")
    path = Path(store.get(ids[0])["path"])
    with patch.object(QMessageBox, "exec", return_value=QMessageBox.Cancel):
        QTest.mouseClick(window.library.grid.viewport(), Qt.LeftButton, pos=point)
    check("cancel_card_delete_preserves_video", path.is_file() and window.player_dialog is None)
    with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
        QTest.mouseClick(window.library.grid.viewport(), Qt.LeftButton, pos=point)
    wait(lambda: not path.exists() and not window.library.storage_busy)
    check("card_delete_removes_video_and_record", store.get(ids[0])["hidden"] and not path.exists())
    wait(lambda: not window.library.pool.active)
    item = store.get(ids[1])
    window.open_media(item)
    wait(lambda: window.player_dialog and window.player_dialog.video.image is not None)
    player = window.player_dialog
    shot("player-delete-action", player)
    with patch.object(QMessageBox, "exec", return_value=QMessageBox.Cancel):
        QTest.mouseClick(player.delete_button, Qt.LeftButton)
    check("cancel_player_delete_keeps_playing", window.player_dialog is player and Path(item["path"]).exists())
    with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
        QTest.mouseClick(player.delete_button, Qt.LeftButton)
    wait(lambda: not Path(item["path"]).exists())
    check("player_releases_file_before_delete", window.player_dialog is None and store.get(ids[1])["hidden"])
    wait(lambda: not window.library.pool.active)
    window.open_media(store.get(album_id))
    gallery = window.player_dialog
    gallery.list.setCurrentRow(0)
    shot("gallery-delete-image", gallery)
    selected = Path(gallery.assets[0]["path"])
    other = Path(gallery.assets[1]["path"])
    with patch.object(QMessageBox, "exec", return_value=QMessageBox.Cancel):
        QTest.mouseClick(gallery.delete_asset_button, Qt.LeftButton)
    check("cancel_image_delete_preserves_album", selected.is_file() and gallery.list.count() == 2)
    with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
        QTest.mouseClick(gallery.delete_asset_button, Qt.LeftButton)
    wait(lambda: not selected.exists() and gallery.list.count() == 1)
    check("image_delete_keeps_other_images", other.is_file() and not selected.exists())
    wait(lambda: not window.library.pool.active)
    store.scan()
    check("deleted_image_does_not_reappear_after_scan", len(gallery_assets(store.get(album_id)["path"], json.loads(store.get(album_id)["metadata"]))) == 1)
    shot("gallery-after-image-delete", gallery)
    with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
        QTest.mouseClick(gallery.delete_asset_button, Qt.LeftButton)
    wait(lambda: not other.exists() and window.player_dialog is None)
    check("deleting_last_image_closes_and_removes_empty_album", store.get(album_id)["hidden"] and not Path(store.get(album_id)["path"]).exists())
    wait(lambda: not window.library.pool.active)
    window.close()
    wait(lambda: not window._jobs_running())
    restarted = DownloadWindow(auto_scan=False, restore_web_login=False, check_updates=False)
    check("restart_preserves_selected_location_and_deletions", restarted.output == target and not restarted.store.rows())
    restarted.close()
    wait(lambda: not restarted._jobs_running())
    report["passed"] = True
finally:
    timer.stop()
    window.closing = True
    window.close()
    wait(lambda: not window._jobs_running())
    (work / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
assert report["passed"]
