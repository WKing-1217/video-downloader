"""Normal interactive web login when another browser protects its cookie store."""
import os
from pathlib import Path
import time

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow

from platform_links import PLATFORMS, domain_matches


class WebLogin(QObject):
    changed = Signal()

    def __init__(self, parent=None, *, storage_path=None, persistent=True):
        super().__init__(parent)
        folder = Path(storage_path) if storage_path else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LocalVideoDownloader/WebProfile"
        if persistent:
            folder.mkdir(parents=True, exist_ok=True)
            self.profile = QWebEngineProfile("local-video-login", self)
            self.profile.setPersistentStoragePath(str(folder))
            self.profile.setCachePath(str(folder / "Cache"))
            self.profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
        else:
            self.profile = QWebEngineProfile(self)
        self.cookies = {}
        self.windows = []
        store = self.profile.cookieStore()
        store.cookieAdded.connect(self.add_cookie)
        store.cookieRemoved.connect(self.remove_cookie)
        store.loadAllCookies()

    def add_cookie(self, cookie):
        if not any(domain_matches(cookie.domain(), p.cookie_domains) for p in PLATFORMS.values()):
            return
        name = bytes(cookie.name()).decode("utf-8", errors="replace")
        key = (cookie.domain(), cookie.path(), name)
        expiry = None if cookie.isSessionCookie() else cookie.expirationDate().toSecsSinceEpoch()
        self.cookies[key] = {"domain": cookie.domain(), "path": cookie.path(), "name": name,
                             "value": bytes(cookie.value()).decode("utf-8", errors="replace"),
                             "secure": cookie.isSecure(), "expires": expiry}
        self.changed.emit()

    def remove_cookie(self, cookie):
        key = (cookie.domain(), cookie.path(), bytes(cookie.name()).decode("utf-8", errors="replace"))
        self.cookies.pop(key, None)
        self.changed.emit()

    def for_platform(self, key):
        return [dict(item) for item in self.cookies.values()
                if domain_matches(item["domain"], PLATFORMS[key].cookie_domains)
                and item["value"] and (not item["expires"] or item["expires"] > time.time())]

    def has_login(self, key):
        return bool({item["name"] for item in self.for_platform(key)}.intersection(PLATFORMS[key].login_cookies))

    def open(self, key, url=None):
        site = PLATFORMS[key]
        window = QMainWindow()
        window.setWindowTitle(f"{site.label} · 网页登录（登录后返回下载器）")
        window.resize(1100, 820)
        view = QWebEngineView(window)
        page = QWebEnginePage(self.profile, view)
        view.setPage(page)
        window.setCentralWidget(view)
        start = {"bilibili": "https://www.bilibili.com/", "douyin": "https://www.douyin.com/",
                 "x": "https://x.com/i/flow/login"}
        view.setUrl(QUrl(url or start[key]))
        self.windows.append(window)
        window.show()

    def close(self):
        for window in self.windows:
            view = window.centralWidget()
            window.close()
            view.page().deleteLater()
            window.deleteLater()
        self.windows.clear()
