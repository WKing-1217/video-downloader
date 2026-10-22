"""The legacy --ui command now exercises v2's paste-to-library workflow."""
import json
import os
from pathlib import Path
import time


def check_ui(web_session=False, sample="", expected=295, min_width=1920, min_height=1080,
             min_audio_bitrate=0, timeout_seconds=300, gallery=False):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    root = Path(__file__).resolve().parents[1]
    work = root / "build" / ("ui-smoke-" + str(time.time_ns()))
    os.environ["LOCALAPPDATA"] = str(work / "preferences")
    os.environ["VIDEO_DOWNLOADER_OUTPUT"] = str(work / "video")
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication
    from app import DownloadWindow
    from desktop_verify import prepare_fonts
    from platform_links import download_link
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication([])
    prepare_fonts()
    window = DownloadWindow(auto_scan=False, restore_web_login=False, check_updates=False)
    window.accounts.auto_login = web_session
    site = download_link(sample)[1]
    if web_session:
        from PySide6.QtNetwork import QNetworkCookie
        from web_login import WebLogin
        window.accounts.source_id = ""
        window.accounts.web = WebLogin(window, persistent=False)
        cookie = QNetworkCookie(b"qt_smoke_only", b"synthetic-not-an-account")
        cookie.setDomain(".bilibili.com")
        cookie.setPath("/")
        window.accounts.web.add_cookie(cookie)
    window.show()
    state = {"passed": False, "platform": site.key, "result": None, "worker_arguments": []}
    started = time.monotonic()
    timer = QTimer()

    def finish(error=None):
        timer.stop()
        state.update(passed=not error, error=error, elapsed=round(time.monotonic() - started, 2))
        work.mkdir(parents=True, exist_ok=True)
        (work / "report.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        window.grab().save(str(work / "download.png"))
        window.install_exit = True
        window.close()

    def tick():
        try:
            if window.downloads.process:
                state["worker_arguments"] = window.downloads.process.arguments()
            task = window.downloads.last
            if time.monotonic() - started > timeout_seconds:
                finish("下载检查超时")
                return
            if task and task.state == "failed":
                finish(task.message)
                return
            if not window.last_result or window.downloads.busy():
                return
            result = state["result"] = window.last_result
            assert result["platform"] == site.key and result.get("library_id"), result
            if gallery:
                assert result["content_type"] == "gallery" and len(result["assets"]) == 5, result
                assert all(asset["full_decode"] and Path(asset["path"]).is_file() for asset in result["assets"])
            else:
                assert abs(result["duration"] - expected) < max(1, expected * .01), result
                assert result["width"] >= min_width and result["height"] >= min_height, result
                assert result["audio_bitrate"] >= min_audio_bitrate and result["audio_codec"] and result["video_codec"], result
            assert window.download_page.progress.value() == 100
            if web_session:
                assert "--session-stdin" in state["worker_arguments"]
                assert "synthetic-not-an-account" not in "\n".join(window.logs)
            finish()
        except Exception as error:
            finish(str(error))

    timer.timeout.connect(tick)
    timer.start(100)
    def paste():
        app.clipboard().setText(sample)
        window.url.paste()
        window.download_page.submit.click()
    QTimer.singleShot(100, paste)
    app.exec()
    print(json.dumps({**state, "directory": str(work)}, ensure_ascii=False, indent=2))
    assert state["passed"], state.get("error")
