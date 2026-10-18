"""Exercise Qt WebEngine cookie events with synthetic data, without logging in."""
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

from PySide6.QtCore import QCoreApplication, QEvent, QTimer, QUrl, Qt
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWidgets import QApplication
from shiboken6 import delete
from web_login import WebLogin


QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
app = QApplication([])
passed = []
errors = []
session = WebLogin(persistent=False)
session.open("bilibili", "about:blank")
store = session.profile.cookieStore()
cookie = QNetworkCookie(b"smoke_test_only", b"synthetic-not-a-login")
cookie.setDomain(".bilibili.com")
cookie.setPath("/")
cookie.setSecure(True)
timer = QTimer()


def verify():
    values = session.for_platform("bilibili")
    if not values:
        return
    timer.stop()
    try:
        assert values[0]["name"] == "smoke_test_only"
        assert not session.has_login("bilibili")
        assert not session.for_platform("x")
        assert session.windows[0].centralWidget().url().toString() == "about:blank"
        passed.append(True)
    except Exception as exc:
        errors.append(str(exc))
    store.deleteCookie(cookie)
    app.quit()


def timeout():
    errors.append("Qt WebEngine cookie event timed out")
    app.quit()


QTimer.singleShot(500, lambda: store.setCookie(cookie, QUrl("https://www.bilibili.com/")))
timer.timeout.connect(verify)
timer.start(100)
QTimer.singleShot(10_000, timeout)
app.exec()
session.close()
QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
delete(session)
app.processEvents()
report = {"passed": bool(passed) and not errors, "errors": errors,
          "checked": ["login window", "cookie event", "platform scoping", "no false login", "window cleanup"]}
Path(__file__).with_name("web-login-smoke-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report))
sys.exit(0 if report["passed"] else 1)
