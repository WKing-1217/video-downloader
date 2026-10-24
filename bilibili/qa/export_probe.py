"""Run real Qt actions and the real local FFmpeg worker in an isolated preview."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORK = ROOT / "build/export-review"
WORK.mkdir(parents=True, exist_ok=True)
os.environ["LOCALAPPDATA"] = str(WORK / "preferences")
os.environ["VIDEO_DOWNLOADER_OUTPUT"] = str(WORK / "media")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox
from app import DownloadWindow, SettingsDialog
from desktop_verify import prepare_fonts
from library_page import MediaModel
from media_library import LibraryStore
from preview_ui import seed_samples
from runtime_paths import configure_tools, save_settings, tool
from ui_theme import METRICS


def main():
    configure_tools()
    media = Path(os.environ["VIDEO_DOWNLOADER_OUTPUT"])
    media.mkdir(parents=True, exist_ok=True)
    fixture = media / "本地视频.mp4"
    if not fixture.exists():
        subprocess.run([tool("ffmpeg"), "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=c=0x45658a:s=640x360:d=4",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", str(fixture)], check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    save_settings(output=str(media), video_format="mp4", image_format="png", audio_bitrate=192)
    app = QApplication([])
    prepare_fonts()
    store = LibraryStore(WORK / f"library-{time.time_ns()}.sqlite3")
    seed_samples(store, media)
    identifier = store.upsert(fixture, {"title": "本地视频 · 提取 MP3", "duration": 4}, completed=True)
    window = DownloadWindow(auto_scan=False, restore_web_login=False, check_updates=False, store=store)
    window.show()
    checks = {}

    def wait(predicate, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(25)
            if predicate():
                return
        raise AssertionError("Export integration timed out: " + str(window.downloads.last))

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks[name] = True

    def shot(name, widget=window):
        QTest.qWait(150)
        assert widget.grab().save(str(WORK / (name + ".png")))

    try:
        wait(lambda: not window.library.scanning)
        wait(lambda: not window.library.pool.active)
        shot("home-video")
        check("home_restored_without_mp3_controls", not window.download_page.findChildren(QComboBox)
              and not hasattr(window.download_page, "local_audio"))
        window.download_page.url.setText("下载页保留的链接")
        window.rail_navigation[3].click()
        check("mp3_has_own_navigation_and_page", window.pages.currentWidget() is window.audio_page
              and window.rail_navigation[3].isChecked() and window.audio_page.local_audio.isVisible())
        window.audio_page.url.setText("提取页保留的链接")
        window.set_page(0)
        check("download_input_survives_mp3_navigation", window.download_page.url.text() == "下载页保留的链接")
        window.set_page(3)
        check("mp3_input_survives_download_navigation", window.audio_page.url.text() == "提取页保留的链接")
        window.audio_page.submit.click()
        check("invalid_mp3_input_stays_on_extraction_page", window.pages.currentIndex() == 3
              and window.audio_page.input_message.isVisible())
        window.set_page(0)
        check("audio_error_does_not_appear_on_home", not window.download_page.input_message.isVisible())
        window.set_page(3)
        check("audio_error_survives_navigation", window.audio_page.input_message.isVisible())
        with patch.object(window.downloads, "submit", return_value=None) as submit:
            window.audio_page.url.setText("https://www.bilibili.com/video/BV1yUFPzKEC7")
            window.audio_page.submit.click()
            check("extraction_link_uses_audio_only", submit.call_args.kwargs.get("mode") == "audio")
            window.set_page(0)
            window.download_page.url.setText("https://www.bilibili.com/video/BV1yUFPzKEC7")
            window.download_page.submit.click()
            check("home_link_keeps_video_mode", submit.call_args.kwargs.get("mode", "video") == "video")
        window.set_page(3)
        window.download_page.url.clear()
        window.audio_page.url.clear()
        window.audio_page.input_message.hide()
        check("both_pages_share_composer_metrics", window.audio_page.composer.objectName() == window.download_page.composer.objectName()
              and window.audio_page.submit.size() == window.download_page.submit.size())
        shot("extract-mp3")
        window.icon_rail.set_expanded(True)
        shot("extract-sidebar-expanded")
        window.icon_rail.set_expanded(False)
        window.resize(METRICS["min_width"], METRICS["min_height"])
        shot("extract-compact")
        check("compact_extraction_controls_fit", window.audio_page.composer.width() <= window.pages.width()
              and window.audio_page.local_audio.geometry().right() <= window.audio_page.width())
        window.resize(1440, 900)
        shot("extract-wide")
        window.resize(METRICS["default_width"], METRICS["default_height"])
        settings = SettingsDialog(window)
        settings.show()
        shot("settings-formats", settings)
        settings.video_format.setCurrentIndex(settings.video_format.findData("mkv"))
        settings.image_format.setCurrentIndex(settings.image_format.findData("webp"))
        settings.audio_bitrate.setCurrentIndex(settings.audio_bitrate.findData(320))
        settings.close()
        settings = SettingsDialog(window)
        check("format_preferences_persist", settings.video_format.currentData() == "mkv"
              and settings.image_format.currentData() == "webp" and settings.audio_bitrate.currentData() == 320)
        settings.video_format.setCurrentIndex(settings.video_format.findData("mp4"))
        settings.image_format.setCurrentIndex(settings.image_format.findData("png"))
        settings.audio_bitrate.setCurrentIndex(settings.audio_bitrate.findData(192))
        settings.resize(700, 560)
        settings.show()
        shot("settings-compact", settings)
        check("settings_can_shrink", settings.size().width() == 700 and settings.size().height() == 560)
        settings.close()
        window.set_page(1)
        row = next(i for i, item in enumerate(window.library.model.rows) if item["id"] == identifier)
        window.library.grid.setCurrentIndex(window.library.model.index(row))
        check("selected_video_enables_mp3", window.library.audio_button.isEnabled())
        shot("library-export")
        original = hashlib.sha256(fixture.read_bytes()).hexdigest()
        window.set_page(3)
        with patch("app.QFileDialog.getOpenFileName", return_value=(str(fixture), "视频文件")) as picker:
            window.audio_page.local_audio.click()
            check("independent_page_opens_local_picker", picker.called)
        wait(lambda: window.downloads.last is not None and window.downloads.last.state in {"done", "failed"}, 60)
        task = window.downloads.last
        check("real_worker_completes_mp3", task.state == "done" and Path(task.result["path"]).suffix == ".mp3")
        check("original_mp4_preserved", hashlib.sha256(fixture.read_bytes()).hexdigest() == original)
        check("export_folder_has_no_json", not list(media.rglob("*.json")))
        check("audio_catalogued", store.get(task.result["library_id"])["kind"] == "audio")
        check("local_extraction_finishes_on_mp3_page", window.pages.currentIndex() == 3
              and window.audio_page.task_panel.isVisible() and window.audio_page.progress.value() == 100)
        shot("mp3-complete")
        window.set_page(0)
        check("audio_progress_does_not_appear_on_home", not window.download_page.task_panel.isVisible())
        shot("home-after-mp3")
        window.set_page(3)
        check("audio_progress_survives_navigation", window.audio_page.task_panel.isVisible()
              and window.audio_page.progress.value() == 100)
        with patch("app.QDesktopServices.openUrl", return_value=True) as opened:
            window.open_media(store.get(task.result["library_id"]))
            check("mp3_uses_default_player", opened.call_args.args[0].isLocalFile()
                  and opened.call_args.args[0].toLocalFile().endswith(".mp3") and window.player_dialog is None)
        window.set_page(1)
        wait(lambda: not window.library.scanning)
        window.library.reload()
        row = next(i for i, item in enumerate(window.library.model.rows) if item["id"] == identifier)
        window.library.grid.setCurrentIndex(window.library.model.index(row))
        window.library.audio_button.click()
        check("library_mp3_action_opens_extraction_page", window.pages.currentIndex() == 3
              and window.rail_navigation[3].isChecked())
        window.set_page(1)
        audio_row = next(i for i, item in enumerate(window.library.model.rows) if item["kind"] == "audio")
        window.library.grid.setCurrentIndex(window.library.model.index(audio_row))
        check("audio_cannot_be_reextracted", not window.library.audio_button.isEnabled())
        window.resize(860, 620)
        shot("library-compact")
        check("compact_toolbar_fits", window.library.delete_button.geometry().right() <= window.library.width())
        window.open_media(store.get(identifier))
        wait(lambda: window.player_dialog.player.duration() > 0)
        window.player_dialog.player.pause()
        check("player_has_mp3_action", window.player_dialog.export_audio_button.isVisible())
        shot("video-player-export", window.player_dialog)
        window.release_media()
        (WORK / "report.json").write_text(json.dumps({"passed": True, "checks": checks}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": True, "checks": checks, "work": str(WORK)}, ensure_ascii=False))
    finally:
        window.install_exit = True
        window.close()
        wait(lambda: not window._jobs_running())


if __name__ == "__main__":
    main()
