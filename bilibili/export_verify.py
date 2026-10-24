"""Opt-in, nonce-marked acceptance of the frozen export UI and bundled worker."""
import hashlib
import json
from pathlib import Path
import time

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox, QScrollArea

from app_version import APP_VERSION
from media_export import full_decode, probe_media
from runtime_paths import FROZEN, data_dir, read_settings, settings_path
from ui_widgets import NoWheelComboBox


def verify_export(app, window, report_path):
    report = Path(report_path).resolve()
    work = report.parent
    state = {"passed": False, "checks": {}, "version": APP_VERSION, "frozen": FROZEN}
    started = time.monotonic()
    stage = ["scan"]
    timer = QTimer(window)
    timer.setInterval(80)
    fixture = {}
    wheel_tests = []

    def check(name, value):
        if not value:
            raise AssertionError(name)
        state["checks"][name] = True

    def digest(path):
        with Path(path).open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    def finish(error=None):
        timer.stop()
        state.update(passed=error is None, error=error, elapsed=round(time.monotonic() - started, 2), logs=list(window.logs))
        report.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        window.install_exit = True
        window.close()

    try:
        config = json.loads((work / "qa-export-fixture.json").read_text(encoding="utf-8"))
        if (config.get("product") != "LocalVideoDownloader" or not config.get("nonce")
                or not data_dir().resolve().is_relative_to(work)):
            raise ValueError("Export verification requires isolated, marked QA data.")
        video = Path(config["video"]).resolve()
        output = Path(config["output"]).resolve()
        if not video.is_relative_to(work) or not output.is_relative_to(work) or not video.is_file():
            raise ValueError("Export fixture paths must remain inside the QA directory.")
        check("expected_version", APP_VERSION == config["expected_version"])
        check("expected_runtime", FROZEN == config.get("expect_frozen", True))
        fixture.update(video=video, output=output, original=digest(video))
        state["nonce"] = config["nonce"]
    except Exception as error:
        QTimer.singleShot(0, lambda message=str(error): finish(message))
        return

    def tick():
        try:
            if time.monotonic() - started > 100:
                raise TimeoutError("Export verification timed out at " + stage[0])
            if stage[0] == "scan":
                if window.library.scanning or window.library.pool.active:
                    return
                rows = window.store.rows()
                video_row = next((item for item in rows if Path(item["path"]).resolve() == fixture["video"]), None)
                if not video_row:
                    return
                fixture["row"] = video_row
                check("home_default_and_no_mp3_controls", window.pages.currentIndex() == 0
                      and not window.download_page.findChildren(QComboBox) and not hasattr(window.download_page, "local_audio"))
                check("four_navigation_entries", len(window.navigation) == 4 and 3 in window.rail_navigation)
                window.rail_navigation[3].click()
                check("independent_extraction_navigation", window.pages.currentWidget() is window.audio_page
                      and window.rail_navigation[3].isChecked())
                window.grab().save(str(work / "frozen-extraction.png"))
                window.download_page.url.setText("保留的下载链接")
                window.audio_page.url.setText("invalid extraction fixture")
                window.audio_page.submit.click()
                check("invalid_audio_feedback_is_separate", window.audio_page.input_message.isVisible()
                      and not window.download_page.input_message.isVisible())
                window.set_page(0)
                check("home_input_is_preserved", window.download_page.url.text() == "保留的下载链接")
                window.set_page(3)
                check("audio_input_is_preserved", window.audio_page.url.text() == "invalid extraction fixture")
                window.audio_page.url.clear()
                window.download_page.url.clear()
                window.audio_page.input_message.hide()
                window.open_settings()
                stage[0] = "settings"
            elif stage[0] == "settings":
                settings = window.settings_dialog
                if not settings or not settings.isVisible():
                    return
                fixture["settings"] = settings
                fixture["scroll"] = settings.findChild(QScrollArea)
                check("all_settings_combos_ignore_wheel", len(settings.findChildren(QComboBox)) == 5
                      and all(isinstance(combo, NoWheelComboBox) for combo in settings.findChildren(QComboBox)))
                check("library_sort_ignores_wheel", isinstance(window.library.sort, NoWheelComboBox))
                if settings.source.count() == 1:
                    settings.source.addItem("隔离验收来源", "qa:source")
                for name in ("video_format", "image_format", "audio_bitrate", "source", "platform"):
                    combo = getattr(settings, name)
                    combo.setCurrentIndex(1)
                    for focused in (False, True):
                        wheel_tests.append((name, combo, focused))
                stage[0] = "wheel"
            elif stage[0] == "wheel":
                pending = fixture.pop("wheel_pending", None)
                if pending:
                    name, focused, bar, before_scroll = pending
                    check("wheel_scrolls_page_" + name + ("_focused" if focused else "_unfocused"), bar.value() != before_scroll)
                if not wheel_tests:
                    settings = fixture["settings"]
                    settings.video_format.setCurrentIndex(0)
                    settings.image_format.setCurrentIndex(0)
                    settings.audio_bitrate.setCurrentIndex(settings.audio_bitrate.findData(192))
                    check("default_formats_and_audio_quality", read_settings().get("video_format") == "mp4"
                          and read_settings().get("image_format") == "png" and read_settings().get("audio_bitrate") == 192)
                    settings.grab().save(str(work / "frozen-settings.png"))
                    settings.close()
                    window.set_page(1)
                    row = next(i for i, item in enumerate(window.library.model.rows) if item["id"] == fixture["row"]["id"])
                    window.library.grid.setCurrentIndex(window.library.model.index(row))
                    check("video_library_mp3_action_available", window.library.audio_button.isEnabled())
                    window.library.audio_button.click()
                    check("library_mp3_routes_to_extraction", window.pages.currentIndex() == 3)
                    stage[0] = "worker"
                    return
                name, combo, focused = wheel_tests.pop(0)
                scroll = fixture["scroll"]
                scroll.ensureWidgetVisible(combo)
                if focused:
                    combo.setFocus()
                else:
                    combo.clearFocus()
                before_index = combo.currentIndex()
                before_settings = settings_path().read_bytes()
                global_point = combo.mapToGlobal(combo.rect().center())
                local_point = fixture["settings"].mapFromGlobal(global_point)
                bar = scroll.verticalScrollBar()
                before_scroll = bar.value()
                direction = -120 if before_scroll < bar.maximum() else 120
                QTest.wheelEvent(fixture["settings"].windowHandle(), local_point, QPoint(0, direction))
                check("wheel_preserves_" + name + ("_focused" if focused else "_unfocused"),
                      combo.currentIndex() == before_index and settings_path().read_bytes() == before_settings)
                fixture["wheel_pending"] = (name, focused, bar, before_scroll)
            elif stage[0] == "worker":
                task = window.downloads.last
                if task and task.state in {"failed", "cancelled"}:
                    raise ValueError(task.message)
                if not task or task.state != "done" or window.downloads.busy():
                    return
                result = task.result
                audio = Path(result["path"])
                check("bundled_worker_was_used", not FROZEN or Path(window.downloads.command_factory([])[0]).name == "download-worker.exe")
                check("real_mp3_file_published", audio.is_file() and audio.suffix.lower() == ".mp3" and audio.is_relative_to(fixture["output"]))
                check("original_mp4_unchanged", digest(fixture["video"]) == fixture["original"])
                check("media_directory_has_no_json", not list(fixture["output"].rglob("*.json")))
                probe = probe_media(audio)
                stream = next(s for s in probe["streams"] if s["codec_type"] == "audio")
                check("mp3_codec_and_bitrate", stream["codec_name"] == "mp3" and int(stream["bit_rate"]) == 192000)
                check("full_duration_preserved", abs(float(probe["format"]["duration"]) - 6) < .3)
                full_decode(audio)
                check("mp3_fully_decodes", True)
                check("audio_catalogued", window.store.get(result["library_id"])["kind"] == "audio")
                check("own_page_shows_completed_progress", window.pages.currentIndex() == 3 and window.audio_page.progress.value() == 100)
                state["result"] = result
                window.grab().save(str(work / "frozen-mp3-complete.png"))
                window.set_page(0)
                check("audio_progress_does_not_leak_home", not window.download_page.task_panel.isVisible())
                window.set_page(3)
                check("audio_progress_survives_navigation", window.audio_page.progress.value() == 100)
                window.open_media(window.store.get(fixture["row"]["id"]))
                stage[0] = "player"
            elif stage[0] == "player":
                player = window.player_dialog
                if not player or player.video.image is None:
                    return
                check("packaged_video_decoder_works", not player.video.image.isNull())
                check("player_has_mp3_export", player.export_audio_button.isVisible())
                player.grab().save(str(work / "frozen-video-player.png"))
                player.export_audio_button.click()
                check("player_export_routes_to_extraction", window.pages.currentIndex() == 3)
                window.release_media()
                finish()
        except Exception as error:
            finish(str(error))

    timer.timeout.connect(tick)
    timer.start()
