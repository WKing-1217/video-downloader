"""Real Qt update UI over a controlled local Release/asset HTTP server."""
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
from dataclasses import replace

root = Path(__file__).resolve().parents[1]
work = root / 'build' / ("v2-update-ui-" + str(time.time_ns()))
work.mkdir()
os.environ["LOCALAPPDATA"] = str(work / "preferences")
os.environ["VIDEO_DOWNLOADER_OUTPUT"] = str(work / "video")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(root))
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app import DownloadWindow
from app_version import REPOSITORY
from desktop_verify import prepare_fonts
from test_v2_updates import ReleaseHandler, PAYLOAD
from http.server import ThreadingHTTPServer
from update_core import UpdateClient

server = ThreadingHTTPServer(("127.0.0.1", 0), ReleaseHandler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
base = f"http://127.0.0.1:{server.server_port}"
ReleaseHandler.version = "2.0.0"
ReleaseHandler.delay = .009
factory = lambda **kwargs: UpdateClient(manifest_url=base + "/manifest", api_url=base + "/api", allow_loopback=True, **kwargs)
app = QApplication([])
prepare_fonts()
window = DownloadWindow(auto_scan=False, restore_web_login=False, check_updates=True, update_client_factory=factory)
window.show()
up = window.updater
checks = {}
beats = [0]
timer = QTimer()
timer.timeout.connect(lambda: beats.__setitem__(0, beats[0] + 1))
timer.start(10)

def wait(condition, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(15)
        if condition():
            return
    raise AssertionError("Timed out: " + str(up.mode) + ": " + window.update_page.transfer_message.text())

def check(name, value):
    assert value, name
    checks[name] = True

try:
    wait(lambda: up.info and not up.busy())
    check("startup_background_check_without_navigation", window.pages.currentIndex() == 0 and beats[0] > 20)
    check("latest_version_is_quiet", up.reminder is None and "已是最新" in window.update_page.status.text())
    ReleaseHandler.version = "2.1.0"
    up.check(manual=False)
    wait(lambda: up.reminder and up.reminder.isVisible() and not up.busy())
    check("new_version_reminder_is_small_and_has_real_notes", up.reminder.width() <= 520 and "真实 Release Notes" in window.update_page.notes.toPlainText())
    up.reminder.later.click()
    check("defer_keeps_main_window_alive", window.isVisible() and not window.closing and window.pages.currentIndex() == 0)
    ReleaseHandler.version = "2.2.0"
    up.check(manual=False)
    wait(lambda: up.reminder.isVisible() and up.info.version == "2.2.0" and not up.busy())
    up.reminder.now.click()
    wait(lambda: up.mode == "downloading" and up.received > 0)
    check("accept_navigates_to_update_page_and_downloads", window.pages.currentIndex() == 2)
    check("real_bytes_speed_percentage_eta_displayed", up.received < up.total and "MB/s" in window.update_page.stats.text() and "剩余" in window.update_page.stats.text())
    before = beats[0]
    wait(lambda: up.mode == "ready" and not up.busy())
    check("download_is_exact_and_ui_remains_responsive", up.installer.read_bytes() == PAYLOAD and beats[0] > before + 10)
    window.grab().save(str(work / "update-ready.png"))
    original = up.installer
    original.write_bytes(b"MZ-previous-verified-installer")
    ReleaseHandler.payload = b"MZ" + b"x" * (len(PAYLOAD) - 2)
    up.download()
    wait(lambda: up.mode == "error" and not up.busy())
    check("hash_failure_preserves_previous_file", original.read_bytes() == b"MZ-previous-verified-installer" and window.update_page.retry_button.isVisible())
    ReleaseHandler.payload = PAYLOAD
    up.retry()
    wait(lambda: up.mode == "ready" and not up.busy())
    check("failed_download_can_retry", original.read_bytes() == PAYLOAD)
    original.unlink()
    ReleaseHandler.mode = "unknown"
    up.info = replace(up.info, size=0)
    up.download()
    wait(lambda: up.mode == "downloading" and up.received > 0 and up.total == 0)
    check("unknown_length_uses_indeterminate_progress", window.update_page.progress.maximum() == 0 and "大小未知" in window.update_page.stats.text())
    up.cancel()
    wait(lambda: up.mode == "cancelled" and not up.busy())
    check("cancel_keeps_application_alive_and_cleans_partial", window.isVisible() and not list(original.parent.glob("*.part")))
    ReleaseHandler.mode = "range"
    up.retry()
    wait(lambda: up.mode == "ready" and not up.busy())
    check("cancelled_download_can_retry", original.read_bytes() == PAYLOAD)
    window.set_page(0)
    ReleaseHandler.fail_all = True
    start = time.monotonic()
    up.check(manual=False)
    wait(lambda: up.mode == "error" and not up.busy())
    check("network_error_is_bounded_and_keeps_homepage", time.monotonic() - start < 10 and window.pages.currentIndex() == 0)
    check("network_error_has_concrete_reason_and_retry", "HTTP 503" in window.update_page.status.text() and not window.update_page.retry_button.isHidden())
    ReleaseHandler.fail_all = False
    up.retry()
    wait(lambda: up.mode == "available" and not up.busy())
    check("failed_check_can_retry", window.pages.currentIndex() == 2)
    check("repository_and_release_are_configured", REPOSITORY == "WKing-1217/video-downloader" and up.info.release_url.startswith("https://github.com/" + REPOSITORY + "/releases/"))
finally:
    timer.stop()
    window.install_exit = True
    window.close()
    wait(lambda: not window._jobs_running())
    server.shutdown()
    server.server_close()
    thread.join()
    report = {"passed": len(checks) == 16 and all(checks.values()), "checks": checks, "controlled_release_server": True, "heartbeat": beats[0]}
    (work / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**report, "directory": str(work)}), flush=True)
assert report["passed"]
