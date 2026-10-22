"""The update page owns details/progress; a small prompt only asks for intent."""
from collections import deque
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid

from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Qt, Signal, QEvent, QPoint
from PySide6.QtGui import QDesktopServices, QTextCursor, QTextCharFormat, QTextFormat, QTextBlockFormat
from PySide6.QtWidgets import QDialog, QHBoxLayout, QMessageBox, QPushButton, QProgressBar, QScrollArea, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget
from app_version import APP_VERSION, RELEASE_PAGE, REPOSITORY
from runtime_paths import APP_DIR, FROZEN, data_dir
from ui_theme import COLORS, SPACE, UPDATE, icon
from ui_widgets import EmptyState, IconBadge, clock_text, panel, size_text, text_label
from update_core import UpdateCancelled, UpdateClient, UpdateError
from update_agent import PRODUCT, write_json


class ReleaseNotes(QTextBrowser):
    """One typography system; the page owns scrolling, the dialog owns its reader."""
    def __init__(self, *, expand=False):
        super().__init__()
        self.expand = expand
        self.setObjectName("releaseNotes")
        self.setOpenExternalLinks(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(SPACE["xs"])
        if expand:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.document().documentLayout().documentSizeChanged.connect(self.fit_content)

    def setMarkdown(self, markdown):
        super().setMarkdown(markdown)
        block = self.document().begin()
        while block.isValid():
            cursor = QTextCursor(block)
            cursor.setPosition(block.position())
            cursor.setPosition(block.position() + block.length() - 1, QTextCursor.KeepAnchor)
            fmt = QTextCharFormat()
            fmt.setProperty(QTextFormat.FontSizeAdjustment, 0)
            fmt.setFontPointSize((UPDATE["notes_heading"] if block.blockFormat().headingLevel() else UPDATE["notes_body"]) * 72 / 96)
            cursor.mergeCharFormat(fmt)
            cursor = QTextCursor(block)
            block_format = cursor.blockFormat()
            block_format.setLineHeight(140, QTextBlockFormat.ProportionalHeight.value)
            block_format.setBottomMargin(SPACE["sm"])
            cursor.setBlockFormat(block_format)
            block = block.next()
        self.fit_content()

    def fit_content(self, *_):
        if self.expand:
            height = max(UPDATE["notes_min_height"], math.ceil(self.document().size().height()) + SPACE["lg"])
            if self.height() != height:
                self.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_content()


class TransferEstimate:
    """Time-based smoothing independent of progress callback frequency."""
    def __init__(self):
        self.samples = deque()
        self.last_render = None
        self.speed = 0.0
        self.eta = None

    def add(self, now, done):
        if self.samples and done < self.samples[-1][1]:
            self.__init__()
        self.samples.append((now, done))
        while len(self.samples) > 2 and now - self.samples[0][0] > 10:
            self.samples.popleft()

    def read(self, now, total):
        if not self.samples:
            return 0, "估算中"
        if now - self.samples[-1][0] >= 5:
            self.speed, self.eta, self.last_render = 0, None, None
            return 0, "等待网络"
        if self.last_render is not None and now - self.last_render < 1:
            return self.speed, clock_text(self.eta) if self.eta is not None else "估算中"
        dt = now - self.last_render if self.last_render is not None else 1
        self.last_render = now
        elapsed = now - self.samples[0][0]
        rate = (self.samples[-1][1] - self.samples[0][1]) / max(elapsed, .001)
        self.speed = rate if not self.speed else self.speed + (rate - self.speed) * (1 - math.exp(-dt / 8))
        if total and elapsed >= 3 and self.speed > 0:
            target = max(0, total - self.samples[-1][1]) / self.speed
            if self.eta is None:
                self.eta = target
            else:
                baseline = max(0, self.eta - dt)
                adjustment = (target - baseline) * (1 - math.exp(-dt / 5))
                self.eta = max(0, baseline + max(-dt, min(3 * dt, adjustment)))
        return self.speed, clock_text(self.eta) if self.eta is not None else "估算中"


class UpdatePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(SPACE["lg"])
        scroll = QScrollArea()
        self.scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        canvas = QWidget()
        canvas.setObjectName("pageCanvas")
        scroll.setWidget(canvas)
        outer.addWidget(scroll, 1)
        layout = QVBoxLayout(canvas)
        layout.setContentsMargins(1, 1, UPDATE["scroll_gutter"], SPACE["lg"])
        layout.setSpacing(SPACE["lg"])
        version, body = panel()
        heading = QHBoxLayout()
        heading.addWidget(text_label("版本信息", role="sectionTitle"))
        heading.addStretch()
        heading.addWidget(text_label("Windows 桌面版", role="caption"))
        body.addLayout(heading)
        row = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(SPACE["xs"])
        left.addWidget(text_label("当前版本", role="muted"))
        self.current = text_label("v" + APP_VERSION, role="display")
        left.addWidget(self.current)
        row.addLayout(left, 1)
        right = QVBoxLayout()
        right.setSpacing(SPACE["xs"])
        right.addWidget(text_label("最新版本", role="muted"))
        self.latest = text_label("尚未检查", role="display")
        right.addWidget(self.latest)
        row.addLayout(right, 1)
        self.check_button = QPushButton("检查更新")
        self.check_button.setObjectName("primary")
        row.addWidget(self.check_button)
        body.addLayout(row)
        self.status = text_label("", role="muted", wrap=True)
        body.addWidget(self.status)
        layout.addWidget(version)
        notes_panel, notes_body = panel()
        notes_panel.setMinimumHeight(220)
        heading = QHBoxLayout()
        heading.addWidget(text_label("更新内容", role="sectionTitle"))
        heading.addStretch()
        heading.addWidget(text_label("官方发布说明", role="caption"))
        notes_body.addLayout(heading)
        self.notes = ReleaseNotes(expand=True)
        self.notes.setObjectName("releaseNotes")
        self.notes.setAccessibleName("官方版本更新内容")
        self.notes.setOpenExternalLinks(True)
        self.notes.setPlaceholderText("版本更新内容会显示在这里。")
        self.notes_empty = EmptyState("暂无更新内容", "", image="nav-update", compact=True)
        self.notes_pages = QStackedWidget()
        self.notes_pages.addWidget(self.notes_empty)
        self.notes_pages.addWidget(self.notes)
        self.notes.textChanged.connect(lambda: self.notes_pages.setCurrentWidget(self.notes if self.notes.toPlainText().strip() else self.notes_empty))
        notes_body.addWidget(self.notes_pages, 1)
        layout.addWidget(notes_panel)
        layout.addStretch()
        self.transfer_panel, transfer = panel()
        self.transfer_title = text_label("更新安装包", role="sectionTitle")
        transfer.addWidget(self.transfer_title)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("更新包下载进度")
        transfer.addWidget(self.progress)
        self.stats = text_label("尚未开始下载", role="muted", wrap=True)
        transfer.addWidget(self.stats)
        self.transfer_message = text_label("", wrap=True)
        transfer.addWidget(self.transfer_message)
        self.transfer_panel.hide()
        layout.insertWidget(1, self.transfer_panel)
        actions = QHBoxLayout()
        self.footer_actions = actions
        actions.setContentsMargins(1, 0, UPDATE["scroll_gutter"], 0)
        self.download_button = QPushButton("下载更新")
        self.download_button.setObjectName("primary")
        self.download_button.hide()
        actions.addWidget(self.download_button)
        self.install_button = QPushButton("安装并重启")
        self.install_button.setObjectName("primary")
        self.install_button.hide()
        actions.addWidget(self.install_button)
        self.cancel_button = QPushButton("取消下载")
        self.cancel_button.hide()
        actions.addWidget(self.cancel_button)
        self.retry_button = QPushButton("重试")
        self.retry_button.hide()
        actions.addWidget(self.retry_button)
        actions.addStretch()
        outer.addLayout(actions)
        links = QHBoxLayout()
        self.github_button = QPushButton("开源项目")
        self.github_button.setObjectName("updateLink")
        self.github_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f"https://github.com/{REPOSITORY}")))
        links.addWidget(self.github_button)
        self.releases_button = QPushButton("历史版本")
        self.releases_button.setObjectName("updateLink")
        self.releases_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(RELEASE_PAGE)))
        links.addWidget(self.releases_button)
        links.setSpacing(SPACE["md"])
        actions.addLayout(links)
        scroll.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self.scroll.viewport() and event.type() == QEvent.Resize:
            viewport_right = watched.mapTo(self, QPoint(watched.width(), 0)).x()
            self.footer_actions.setContentsMargins(1, 0, max(0, self.width() - viewport_right) + UPDATE["scroll_gutter"], 0)
        return super().eventFilter(watched, event)


class UpdateJob(QThread):
    checked = Signal(object)
    downloaded = Signal(object)
    failed = Signal(str)
    progress = Signal(object)
    stage = Signal(str)
    cancelled_signal = Signal()

    def __init__(self, info=None, client_factory=UpdateClient, folder=None):
        super().__init__()
        self.info, self.client_factory = info, client_factory
        self.folder = folder or data_dir() / "updates"
        self.cancelled = threading.Event()
        self.last_progress = 0

    def run(self):
        client = self.client_factory(cancelled=self.cancelled)
        try:
            if self.info is None:
                self.checked.emit(client.check())
            else:
                def progress(done, total):
                    now = time.monotonic()
                    if now - self.last_progress >= 0.1 or done == total:
                        self.progress.emit((done, total, now))
                        self.last_progress = now
                self.downloaded.emit(client.download(self.info, self.folder, progress, self.stage.emit))
        except UpdateCancelled:
            self.cancelled_signal.emit()
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            client.close()


class UpdateReminder(QDialog):
    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.setWindowTitle("软件更新")
        self.setModal(True)
        self.setSizeGripEnabled(True)
        screen = self.screen().availableGeometry()
        self.setMinimumSize(min(UPDATE["dialog_min_width"], screen.width()), min(UPDATE["dialog_min_height"], screen.height() - 80))
        self.resize(min(UPDATE["dialog_width"], screen.width() - 64), min(UPDATE["dialog_height"], screen.height() - 80))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xxl"], SPACE["xxl"], SPACE["xxl"], SPACE["xxl"])
        layout.setSpacing(SPACE["lg"])
        row = QHBoxLayout()
        row.setSpacing(SPACE["md"])
        row.addWidget(IconBadge("nav-update", tone="active"))
        row.addWidget(text_label("发现新版本 v" + info.version, role="sectionTitle"), 1)
        layout.addLayout(row)
        layout.addWidget(text_label("当前版本 v" + APP_VERSION, role="muted"))
        notes = ReleaseNotes()
        self.notes = notes
        notes.setMarkdown(info.notes)
        notes.setOpenExternalLinks(True)
        layout.addWidget(notes, 1)
        row = QHBoxLayout()
        row.addStretch()
        self.later = QPushButton("暂不更新")
        self.later.clicked.connect(self.reject)
        row.addWidget(self.later)
        self.now = QPushButton("立即更新")
        self.now.setObjectName("primary")
        self.now.clicked.connect(self.accept)
        row.addWidget(self.now)
        layout.addLayout(row)


def prepare_install(info, installer, *, roots, app_dir=APP_DIR, user_data=None):
    installer = Path(installer).resolve()
    user_data = Path(user_data or data_dir()).resolve()
    cache = user_data / "updates"
    with installer.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if (info.sha256 and digest != info.sha256) or (info.size and installer.stat().st_size != info.size):
        raise UpdateError("更新包已改变，请重新下载。")
    helper = Path(app_dir) / "update-helper.exe"
    if not helper.is_file():
        raise UpdateError("独立更新助手缺失，请重新安装当前版本。")
    nonce = uuid.uuid4().hex
    runner = cache / ("helper-" + nonce + ".exe")
    shutil.copy2(helper, runner)
    plan = {"schema": 1, "product": PRODUCT, "version": info.version, "previous_version": APP_VERSION,
            "app_dir": str(Path(app_dir).resolve()), "cache_dir": str(cache), "data_dir": str(user_data),
            "installer": str(installer), "sha256": digest, "size": installer.stat().st_size,
            "old_pid": os.getpid(), "nonce": nonce, "handshake": str(cache / ("ready-" + nonce + ".json")),
            "helper_ready": str(cache / ("helper-ready-" + nonce + ".json")),
            "protected_roots": list(roots), "manage_registry": True}
    target = cache / ("plan-" + nonce + ".json")
    write_json(target, plan)
    return runner, target


class UpdateController(QObject):
    available_changed = Signal(bool)
    navigate = Signal()
    log = Signal(str)

    def __init__(self, page, window, *, client_factory=UpdateClient):
        super().__init__(window)
        self.page, self.window = page, window
        self.client_factory = client_factory
        self.info = None
        self.installer = None
        self.job = None
        self.mode = "idle"
        self.reminder = None
        self.prompted = set()
        self.estimate = TransferEstimate()
        self.received = self.total = 0
        self.installing = False
        self.pending_download = False
        self.retry_download = False
        self.helper_process = None
        self.page.check_button.clicked.connect(lambda: self.check(manual=True))
        self.page.download_button.clicked.connect(self.download)
        self.page.cancel_button.clicked.connect(self.cancel)
        self.page.retry_button.clicked.connect(self.retry)
        self.page.install_button.clicked.connect(self.install)
        self.stats_timer = QTimer(self)
        self.stats_timer.setInterval(250)
        self.stats_timer.timeout.connect(self.render_stats)

    def busy(self):
        return bool(self.job and self.job.isRunning())

    def _start(self, job, mode):
        self.job, self.mode = job, mode
        self.page.check_button.setEnabled(False)
        self.page.download_button.setEnabled(False)
        self.page.retry_button.hide()
        job.failed.connect(self.failed)
        job.cancelled_signal.connect(self.cancelled)
        job.finished.connect(lambda: self._finished(job))
        job.start()

    def check(self, *, manual=False):
        if self.window.closing or self.busy() or self.installing:
            return
        if manual:
            self.navigate.emit()
        self.page.status.setText("正在检查新版本…")
        job = UpdateJob(client_factory=self.client_factory)
        job.checked.connect(lambda info: self.checked(info, manual))
        self._start(job, "checking")

    def _finished(self, job):
        if self.job is not job:
            job.deleteLater()
            return
        self.job = None
        self.page.check_button.setEnabled(not self.installing)
        self.page.download_button.setEnabled(True)
        self.page.cancel_button.hide()
        self.stats_timer.stop()
        job.deleteLater()
        if self.pending_download and not self.window.closing:
            self.pending_download = False
            QTimer.singleShot(0, self.download)

    def checked(self, info, manual):
        if not self.info or self.info.version != info.version:
            self.installer = None
            self.page.install_button.hide()
        self.info = info
        self.page.latest.setText("v" + info.version)
        self.page.notes.setMarkdown(info.notes)
        self.page.status.setText("发现可用的新版本" if info.available else "已是最新版本，无需更新。")
        self.page.download_button.setVisible(info.available and not self.installer)
        self.available_changed.emit(info.available)
        self.mode = "available" if info.available else "latest"
        if info.available and not manual and info.version not in self.prompted:
            self.prompted.add(info.version)
            QTimer.singleShot(0, self.show_reminder)

    def show_reminder(self):
        if not self.info or not self.info.available or self.window.closing:
            return
        self.reminder = UpdateReminder(self.info, self.window)
        self.reminder.accepted.connect(self.accept_reminder)
        self.reminder.show()

    def accept_reminder(self):
        self.navigate.emit()
        if self.busy():
            self.pending_download = True
        else:
            QTimer.singleShot(0, self.download)

    def download(self):
        if self.window.closing or self.busy() or not self.info or not self.info.available:
            return
        self.page.transfer_panel.show()
        self.page.transfer_title.setText("正在下载 v" + self.info.version)
        self.page.transfer_message.setText("正在连接官方安装包…")
        self.page.progress.setRange(0, 0)
        self.page.install_button.hide()
        self.page.download_button.hide()
        self.page.cancel_button.show()
        self.page.cancel_button.setEnabled(True)
        self.estimate = TransferEstimate()
        self.received, self.total = 0, self.info.size
        self.estimate.add(time.monotonic(), 0)
        self.stats_timer.start()
        self.render_stats()
        job = UpdateJob(info=self.info, client_factory=self.client_factory)
        job.progress.connect(self.progress)
        job.stage.connect(self.page.transfer_message.setText)
        job.downloaded.connect(self.ready)
        self._start(job, "downloading")

    def progress(self, values):
        done, total, now = values
        if done < self.received:
            self.estimate = TransferEstimate()
        self.received, self.total = done, total
        self.estimate.add(now, done)
        self.page.progress.setRange(0, 100 if total else 0)
        if total:
            self.page.progress.setValue(min(100, round(done * 100 / total)))
        self.render_stats()

    def render_stats(self):
        now = time.monotonic()
        speed, eta = self.estimate.read(now, self.total)
        total = size_text(self.total) if self.total else "大小待确认"
        percent = f"{self.received / self.total:.0%}" if self.total else "大小未知"
        if not self.total:
            eta = "—"
        self.page.stats.setText(f"{size_text(self.received)} / {total} · {speed / 1024 ** 2:.1f} MB/s · {percent} · 剩余 {eta}")

    def ready(self, installer):
        self.installer = Path(installer)
        self.stats_timer.stop()
        self.page.stats.setText(f"{size_text(self.received)} / {size_text(self.total)} · 100%")
        self.mode = "ready"
        self.page.progress.setRange(0, 100)
        self.page.progress.setValue(100)
        self.page.transfer_title.setText("v" + self.info.version + " 已下载")
        self.page.transfer_message.setText("安装包已通过 SHA-256 校验。安装将关闭本程序，完成后自动打开新版。" if self.info.sha256
                                           else "安装包已下载并检查文件大小；发布方未提供 SHA-256。安装后将自动打开新版。")
        self.page.install_button.show()
        self.page.retry_button.hide()

    def failed(self, message):
        self.retry_download = self.mode != "checking"
        self.log.emit("更新：" + message)
        if self.mode == "checking":
            self.page.status.setText("检查失败：" + message)
        else:
            self.page.transfer_message.setText(message + " 可重试，或打开官方 Releases 下载。")
        self.mode = "error"
        self.page.retry_button.show()

    def retry(self):
        if self.retry_download and self.info and self.info.available:
            self.download()
        else:
            self.check(manual=True)

    def cancel(self):
        if self.job:
            self.job.cancelled.set()
            self.page.transfer_message.setText("正在取消下载…")
            self.page.cancel_button.setEnabled(False)

    def cancelled(self):
        self.retry_download = True
        self.mode = "cancelled"
        self.page.transfer_message.setText("已取消更新，原程序未改动。")
        self.page.retry_button.show()

    def install(self):
        if not self.installer or not self.info or self.busy():
            return
        if self.window.downloads.busy():
            self.page.transfer_message.setText("请先完成或取消视频任务，再安装更新。")
            return
        if getattr(self.window, "storage", None) and (self.window.storage.running or self.window.storage.service.pending()):
            self.page.transfer_message.setText("请先完成视频目录迁移，再安装更新。")
            return
        if not FROZEN:
            self.page.transfer_message.setText("当前是开发环境，请使用打包后的程序验证正式安装；下载功能不受影响。")
            return
        question = QMessageBox.question(self.window, "安装并重启", "即将关闭视频下载器并安装新版本，完成后会自动重新打开。\n视频、历史记录和登录配置会保留。是否继续？",
                                       QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if question != QMessageBox.Yes:
            return
        self.installing = True
        self.page.install_button.setEnabled(False)
        self.page.transfer_message.setText("正在准备独立更新助手…")
        roots = self.window.store.roots()
        self.window.background.submit(lambda: prepare_install(self.info, self.installer, roots=roots), self._prepared, self._prepare_failed)

    def _prepared(self, result):
        try:
            runner, plan = result
            self.helper_process = subprocess.Popen([str(runner), "--plan", str(plan)], cwd=runner.parent,
                                                    env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"},
                                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.helper_plan = json.loads(plan.read_text(encoding="utf-8"))
            self.helper_deadline = time.monotonic() + 20
            self.helper_timer = QTimer(self)
            self.helper_timer.setInterval(100)
            self.helper_timer.timeout.connect(self._helper_ready)
            self.helper_timer.start()
        except OSError as error:
            self._prepare_failed(str(error))

    def _helper_ready(self):
        try:
            status = json.loads(Path(self.helper_plan["helper_ready"]).read_text(encoding="utf-8"))
            if status.get("nonce") == self.helper_plan["nonce"]:
                self.helper_timer.stop()
                self.page.transfer_message.setText("正在关闭旧程序并备份安装，新版将自动启动。")
                self.window.install_exit = True
                self.window.close()
                return
        except (OSError, ValueError):
            pass
        if self.helper_process.poll() is not None or time.monotonic() > self.helper_deadline:
            self.helper_timer.stop()
            if self.helper_process.poll() is None:
                self.helper_process.terminate()
            self._prepare_failed("独立更新助手未能就绪，当前程序继续运行。")

    def _prepare_failed(self, message):
        self.installing = False
        self.page.install_button.setEnabled(True)
        self.page.transfer_message.setText("安装未开始：" + message)

    def shutdown(self):
        self.pending_download = False
        if self.job:
            self.job.cancelled.set()
        self.stats_timer.stop()
        if self.reminder:
            self.reminder.close()

