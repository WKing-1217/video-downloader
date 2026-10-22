"""Opt-in acceptance of the frozen application against a marked QA directory."""
import hashlib
import json
from pathlib import Path
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from media_library import gallery_assets
from runtime_paths import data_dir, read_settings


def verify_storage(app, window, report_path):
    report = Path(report_path).resolve()
    work = report.parent
    state = {"passed": False, "checks": {}, "started": time.time()}
    timer = QTimer(window)
    timer.setInterval(40)
    stage = ["scan"]
    fixtures = {}
    started = time.monotonic()

    def finish(error=None):
        timer.stop()
        state.update(passed=not bool(error), error=error, elapsed=round(time.monotonic() - started, 2))
        report.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        window.install_exit = True
        window.close()

    def check(name, value):
        if not value:
            raise AssertionError(name)
        state["checks"][name] = True

    def file_hash(path):
        with Path(path).open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    def confirm():
        dialog = app.activeModalWidget()
        if isinstance(dialog, QMessageBox):
            dialog.button(QMessageBox.Yes).click()

    try:
        config = json.loads((work / "qa-storage-fixture.json").read_text(encoding="utf-8"))
        if (config.get("product") != "LocalVideoDownloader" or not config.get("nonce")
                or not data_dir().resolve().is_relative_to(work)):
            raise ValueError("Storage verification requires isolated, marked QA data.")
        old, target = Path(config["initial"]), Path(config["target"])
        if not old.is_relative_to(work) or not target.is_relative_to(work):
            raise ValueError("Storage fixture paths must remain in the QA directory.")
        state["nonce"] = config["nonce"]
    except Exception as error:
        QTimer.singleShot(0, lambda message=str(error): finish(message))
        return

    def tick():
        try:
            if time.monotonic() - started > 90:
                raise TimeoutError("Frozen storage verification timed out at " + stage[0])
            if stage[0] == "scan":
                rows = window.store.rows()
                if len(rows) < 2 or window.library.scanning or window.library.pool.active:
                    return
                check("installer_choice_used_on_first_launch", window.output == old and read_settings()["output"] == str(old))
                check("fixtures_are_isolated", all(Path(row["path"]).is_relative_to(old) for row in rows))
                fixtures["video"] = next(row for row in rows if row["kind"] == "video")
                fixtures["album"] = next(row for row in rows if row["kind"] == "gallery")
                fixtures["hashes"] = {row["id"]: file_hash(row["path"]) for row in rows if row["kind"] == "video"}
                fixtures["images"] = [file_hash(asset["path"]) for asset in gallery_assets(
                    fixtures["album"]["path"], json.loads(fixtures["album"]["metadata"]))]
                stage[0] = "migration"
                window.choose_output(str(target))
            elif stage[0] == "migration":
                if window.storage.running or window.library.pool.active:
                    return
                check("frozen_migration_completed", not window.storage.service.pending() and window.output == target)
                check("old_directory_cleaned", not old.exists())
                video = window.store.get(fixtures["video"]["id"])
                check("video_bytes_and_history_preserved", file_hash(video["path"]) == fixtures["hashes"][video["id"]]
                      and video["completed"] == fixtures["video"]["completed"])
                album = window.store.get(fixtures["album"]["id"])
                images = gallery_assets(album["path"], json.loads(album["metadata"]))
                check("album_bytes_preserved", [file_hash(asset["path"]) for asset in images] == fixtures["images"])
                check("selected_location_saved", read_settings()["output"] == str(target))
                window.storage.dialog.close()
                fixtures["new_video"] = Path(video["path"])
                window.open_media(video)
                stage[0] = "player"
            elif stage[0] == "player":
                player = window.player_dialog
                if not player or player.video.image is None:
                    return
                check("frozen_decoder_plays_migrated_video", not player.video.image.isNull())
                player.grab().save(str(work / "frozen-player.png"))
                stage[0] = "delete-video"
                QTimer.singleShot(100, confirm)
                player.delete_button.click()
            elif stage[0] == "delete-video":
                if fixtures["new_video"].exists() or window.library.storage_busy or window.library.pool.active:
                    return
                check("frozen_player_delete_removes_video", window.store.get(fixtures["video"]["id"])["hidden"] == 1)
                window.open_media(window.store.get(fixtures["album"]["id"]))
                gallery = window.player_dialog
                fixtures["selected_image"] = Path(gallery.assets[0]["path"])
                stage[0] = "delete-image"
                QTimer.singleShot(100, confirm)
                gallery.delete_asset_button.click()
            elif stage[0] == "delete-image":
                if fixtures["selected_image"].exists() or window.library.storage_busy:
                    return
                gallery = window.player_dialog
                check("frozen_single_image_delete_keeps_other_image", gallery.list.count() == 1 and Path(gallery.assets[0]["path"]).is_file())
                album = window.store.get(fixtures["album"]["id"])
                check("frozen_receipt_updated", len(json.loads((Path(album["path"]) / "作品信息.json").read_text(encoding="utf-8"))["assets"]) == 1)
                gallery.grab().save(str(work / "frozen-gallery.png"))
                window.grab().save(str(work / "frozen-library.png"))
                finish()
        except Exception as error:
            finish(str(error))

    timer.timeout.connect(tick)
    timer.start()
