"""Opt-in isolated acceptance probe for the real, packaged Qt application."""
import json
import os
from pathlib import Path
import sys
import time
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase


def prepare_fonts():
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyhbd.ttc", "seguiemj.ttf"):
        if (fonts / name).is_file():
            QFontDatabase.addApplicationFont(str(fonts / name))


def verify(app, window, target):
    report = Path(target).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    state = {"passed": False, "default_page": window.pages.currentIndex(), "navigation_count": len(window.navigation),
             "heartbeat": 0, "frames": 0, "result": None, "started": time.time()}
    started = time.monotonic()
    stage = ["download"]
    timer = QTimer(window)
    timer.setInterval(50)
    heartbeat = QTimer(window)
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: state.update(heartbeat=state["heartbeat"] + 1))
    heartbeat.start()

    def finish(error=None):
        timer.stop()
        heartbeat.stop()
        state.update(elapsed=round(time.monotonic() - started, 2), error=error, logs=list(window.logs))
        state["passed"] = bool(not error and state["frames"] and state["result"] and state["default_page"] == 0)
        report.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        window.install_exit = True
        window.close()

    def frame(value):
        if value.isValid():
            state["frames"] += 1

    def tick():
        try:
            if time.monotonic() - started > 360:
                finish("下载或播放检查超时")
                return
            task = window.downloads.last
            if stage[0] == "download":
                if task and task.state in {"failed", "cancelled"}:
                    finish(task.message)
                    return
                if not window.last_result or window.downloads.busy():
                    return
                state["result"] = window.last_result
                state["worker"] = window.downloads.command_factory([])[0]
                window.grab().save(str(report.with_name(report.stem + "-download.png")))
                window.set_page(1)
                stage[0] = "library"
            elif stage[0] == "library":
                item = next((row for row in window.store.rows() if row["id"] == state["result"].get("library_id")), None)
                if not item or not item.get("thumb"):
                    return
                state["library_count"] = len(window.store.rows())
                window.grab().save(str(report.with_name(report.stem + "-library.png")))
                window.open_media(item)
                window.player_dialog.video.videoSink().videoFrameChanged.connect(frame)
                stage[0] = "player"
            elif stage[0] == "player" and state["frames"] >= 3:
                window.player_dialog.grab().save(str(report.with_name(report.stem + "-player.png")))
                finish()
        except Exception as error:
            finish(str(error))

    timer.timeout.connect(tick)
    timer.start()
    link = next((argument for argument in sys.argv[1:] if argument.startswith(("https://", "http://"))), None)
    if not link:
        QTimer.singleShot(0, lambda: finish("验证模式需要视频链接参数"))
    else:
        def paste():
            app.clipboard().setText(link)
            window.url.paste()
            window.download_page.submit.click()
        QTimer.singleShot(0, paste)
