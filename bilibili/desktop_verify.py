"""Exercise the installed Qt app and its bundled worker without Python tooling."""
import json
import os
from pathlib import Path
from PySide6.QtCore import QProcess, QTimer
from PySide6.QtGui import QFontDatabase


def prepare_fonts():
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyhbd.ttc", "seguiemj.ttf"):
        if (fonts / name).is_file():
            QFontDatabase.addApplicationFont(str(fonts / name))


def verify(app, window, target):
    report = Path(target).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    timer = QTimer(window)

    def finish():
        if window.process is None or window.process.state() != QProcess.NotRunning:
            return
        timer.stop()
        result = window.result
        passed = bool(result and window.open_file.isEnabled() and window.progress.value() == 100)
        payload = {"passed": passed, "title": window.title.text(), "status": window.status.text(),
                   "details": window.details.text(), "worker": window.process.program(),
                   "result": result, "logs": window.logs.toPlainText()}
        report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        window.grab().save(str(report.with_suffix(".png")))
        app.exit(0 if passed else 1)

    def timeout():
        if not report.exists():
            window.stop_process()
            report.write_text(json.dumps({"passed": False, "error": "timeout", "status": window.status.text()}, ensure_ascii=False), encoding="utf-8")
            app.exit(2)

    timer.timeout.connect(finish)
    timer.start(200)
    QTimer.singleShot(240_000, timeout)
    QTimer.singleShot(0, window.start_download)
