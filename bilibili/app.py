"""Windows v2: paste downloads, a local media library, and an update workbench."""
from collections import deque
import json
import os
from pathlib import Path
import sys

from PySide6.QtCore import QProcess, QTimer, Qt, QUrl, Signal, QSize
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
    QGraphicsDropShadowEffect, QHBoxLayout, QLineEdit, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QStackedWidget, QToolButton, QVBoxLayout, QWidget, QFrame, QSizePolicy)

from app_version import APP_VERSION
from async_jobs import BackgroundPool
from download_service import AccountService, DownloadManager
from library_page import LibraryPage
from media_library import LibraryStore
from platform_links import PLATFORMS, download_link
from runtime_paths import APP_DIR, FROZEN, data_dir, output_dir, read_settings, save_output, save_settings
from ui_theme import COLORS, DIALOG, HOME, METRICS, RAIL, ROOT, SPACE, icon, stylesheet
from ui_navigation import MediaSearchDialog, NavigationSidebar
from ui_widgets import (ComposerFrame, ElidedLabel, IconBadge, LoginSourceComboBox,
    PasteLinkEdit, RecentDelegate, RecentList, clock_text, divider, panel, set_tone, size_text, text_label)
from updater import UpdateController, UpdatePage


class DownloadPage(QWidget):
    show_library = Signal()
    open_requested = Signal(object)
    submitted = Signal(str)
    retry = Signal()
    login = Signal()
    cancel = Signal()
    clear_queue = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        canvas = QWidget()
        canvas.setObjectName("pageCanvas")
        self.scroll.setWidget(canvas)
        outer.addWidget(self.scroll)
        center = QHBoxLayout(canvas)
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(0)
        center.addStretch()
        self.composition = QWidget()
        self.composition.setMaximumWidth(HOME["content_width"])
        self.composition.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self.composition)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(HOME["greeting_gap"])
        layout.addStretch(1)
        self.greeting = text_label("你好，今天想保存什么？", role="greeting")
        self.greeting.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.greeting)
        entry = QVBoxLayout()
        entry.setSpacing(SPACE["sm"])
        self.composer = ComposerFrame()
        self.composer.setMinimumHeight(HOME["composer_height"])
        shadow = QGraphicsDropShadowEffect(self.composer)
        shadow.setBlurRadius(HOME["shadow_blur"])
        shadow.setOffset(0, HOME["shadow_offset"])
        shadow.setColor(QColor(0, 0, 0, HOME["shadow_alpha"]))
        self.composer.setGraphicsEffect(shadow)
        row = QHBoxLayout(self.composer)
        pad = HOME["composer_inset"]
        row.setContentsMargins(pad, pad, pad, pad)
        row.setSpacing(SPACE["sm"])
        self.url = PasteLinkEdit()
        self.url.setObjectName("linkInput")
        self.url.setPlaceholderText("输入链接")
        self.url.setAccessibleName("视频链接")
        self.url.setMinimumWidth(0)
        self.url.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(self.url, 1)
        self.paste = QToolButton()
        self.paste.setObjectName("pasteAction")
        self.paste.setIcon(icon("clipboard", COLORS["text"]))
        self.paste.setIconSize(QSize(METRICS["nav_icon"], METRICS["nav_icon"]))
        self.paste.setFixedSize(HOME["action_size"], HOME["action_size"])
        self.paste.setToolTip("粘贴")
        self.paste.setAccessibleName("粘贴链接")
        self.paste.clicked.connect(self.url.paste)
        row.addWidget(self.paste)
        self.submit = QPushButton()
        self.submit.setObjectName("sendAction")
        self.submit.setIcon(icon("arrow-up", COLORS["white"]))
        self.submit.setIconSize(QSize(METRICS["nav_icon"], METRICS["nav_icon"]))
        self.submit.setFixedSize(HOME["action_size"], HOME["action_size"])
        self.submit.setToolTip("下载")
        self.submit.setAccessibleName("开始下载")
        self.submit.clicked.connect(lambda: self.submitted.emit(self.url.text()))
        self.url.returnPressed.connect(lambda: self.submitted.emit(self.url.text()))
        row.addWidget(self.submit)
        entry.addWidget(self.composer)
        self.input_message = text_label("", role="error", wrap=True)
        self.input_message.hide()
        self.url.textEdited.connect(self.input_message.hide)
        entry.addWidget(self.input_message)
        layout.addLayout(entry)
        self.task_panel, body = panel("taskPanel")
        body.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        body.setSpacing(SPACE["sm"])
        heading = QHBoxLayout()
        heading.setSpacing(SPACE["md"])
        self.task_icon = IconBadge("nav-download")
        self.task_icon.setFixedSize(SPACE["page"], SPACE["page"])
        heading.addWidget(self.task_icon)
        labels = QVBoxLayout()
        labels.setSpacing(SPACE["xs"])
        self.task_title = ElidedLabel("", role="taskTitle")
        labels.addWidget(self.task_title)
        self.task_status = text_label("", role="muted", wrap=True)
        labels.addWidget(self.task_status)
        heading.addLayout(labels, 1)
        self.task_badge = text_label("", role="statusBadge")
        heading.addWidget(self.task_badge, 0, Qt.AlignTop)
        body.addLayout(heading)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("下载进度")
        self.progress.setValue(0)
        self.progress.hide()
        body.addWidget(self.progress)
        self.details = text_label("", role="muted", wrap=True)
        self.details.hide()
        body.addWidget(self.details)
        actions = QHBoxLayout()
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.hide()
        actions.addWidget(self.cancel_button)
        self.retry_button = QPushButton("重试")
        self.retry_button.setObjectName("primary")
        self.retry_button.clicked.connect(self.retry)
        self.retry_button.hide()
        actions.addWidget(self.retry_button)
        self.login_button = QPushButton("登录")
        self.login_button.clicked.connect(self.login)
        self.login_button.hide()
        actions.addWidget(self.login_button)
        self.view_button = QPushButton("查看")
        self.view_button.setObjectName("link")
        self.view_button.clicked.connect(self.show_library)
        self.view_button.hide()
        actions.addWidget(self.view_button)
        actions.addStretch()
        body.addLayout(actions)
        queue_row = QHBoxLayout()
        self.queue_label = text_label("", role="muted", wrap=True)
        self.queue_label.hide()
        queue_row.addWidget(self.queue_label, 1)
        self.clear_queue_button = QPushButton("清空")
        self.clear_queue_button.setObjectName("link")
        self.clear_queue_button.clicked.connect(self.clear_queue)
        self.clear_queue_button.hide()
        queue_row.addWidget(self.clear_queue_button)
        body.addLayout(queue_row)
        self.task_panel.hide()
        layout.addWidget(self.task_panel)
        self.recent = RecentList()
        self.recent.setObjectName("recentList")
        self.recent.setAccessibleName("最近三个作品")
        self.recent.setItemDelegate(RecentDelegate(self.recent))
        self.recent.open_requested.connect(self.open_recent)
        layout.addWidget(self.recent)
        layout.addStretch(1)
        center.addWidget(self.composition, 1)
        center.addStretch()

    def open_recent(self, item):
        row = item.data(RecentDelegate.Row)
        if row:
            self.open_requested.emit(row)

    def update_recent(self, identifier, values):
        for number in range(self.recent.count()):
            row = self.recent.item(number)
            record = row.data(RecentDelegate.Row)
            if record and record["id"] == identifier:
                row.setData(RecentDelegate.Row, {**record, **values})

    def reject_input(self, message):
        self.input_message.setText(message)
        self.input_message.show()

    def render(self, task):
        self.task_panel.show()
        self.task_title.setText(task.title)
        self.task_status.setText(task.message)
        active = task.state in {"running", "saving"}
        percentage = min(100, round(task.downloaded * 100 / task.total)) if task.total else 0
        label, tone, image = {
            "running": ("下载中", "active", "nav-download"),
            "saving": ("正在入库", "active", "nav-library"),
            "done": ("已完成", "success", "check"),
            "failed": ("下载失败", "danger", "alert"),
            "cancelled": ("已取消", "neutral", "nav-download"),
        }.get(task.state, ("等待中", "neutral", "nav-download"))
        self.task_badge.setText(label)
        set_tone(self.task_badge, tone)
        set_tone(self.progress, tone)
        self.task_icon.set_icon(image, tone)
        self.progress.setVisible(active or task.state == "done")
        self.cancel_button.setVisible(task.state == "running")
        self.cancel_button.setEnabled(not task.cancelled)
        self.retry_button.setVisible(task.state in {"failed", "cancelled"})
        self.login_button.setVisible(task.state == "failed")
        self.view_button.setVisible(task.state == "done")
        if active and not task.total:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(100 if task.state == "done" else percentage)
        if task.state == "done" and task.result:
            result = task.result
            self.details.setText((clock_text(result.get("duration")) + " · " if result.get("duration") else "图文作品 · ") + size_text(result["size"]))
        elif task.total:
            details = f"{size_text(task.downloaded)} / {size_text(task.total)} · {percentage}%"
            if active:
                details += f" · {task.speed / 1024 ** 2:.1f} MB/s"
                if task.eta is not None:
                    details += " · 剩余 " + clock_text(task.eta)
            self.details.setText(details)
        else:
            self.details.setText("")
        self.details.setVisible(bool(self.details.text()))

    def render_recent(self, rows):
        current = self.recent.currentRow()
        self.recent.clear()
        for item in rows[:3]:
            row = QListWidgetItem(item["title"])
            row.setData(RecentDelegate.Row, item)
            row.setToolTip(item["title"])
            self.recent.addItem(row)
        self.recent.setVisible(bool(rows))
        self.recent.update_grid()
        if rows and current >= 0:
            self.recent.setCurrentRow(min(current, len(rows[:3]) - 1))


class SettingsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.accounts = window, window.accounts
        self.setWindowTitle("设置与账号")
        self.resize(DIALOG["settings_width"], DIALOG["settings_height"])
        self.setMinimumSize(DIALOG["settings_min_width"], DIALOG["settings_min_height"])
        self.setSizeGripEnabled(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(DIALOG["inset"], DIALOG["inset"], DIALOG["inset"], DIALOG["inset"])
        layout.setSpacing(SPACE["xxl"])
        layout.addWidget(text_label("设置", role="pageTitle"))
        account, body = panel()
        body.addWidget(text_label("账号与登录", role="sectionTitle"))
        self.auto_login = QCheckBox("自动读取本机浏览器的登录状态")
        self.auto_login.setChecked(self.accounts.auto_login)
        body.addWidget(self.auto_login)
        row = QHBoxLayout()
        row.addWidget(text_label("登录来源"))
        self.source = LoginSourceComboBox()
        self.source.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.source.setMinimumContentsLength(12)
        row.addWidget(self.source, 1)
        body.addLayout(row)
        self.status = text_label(self.accounts.status, role="muted", wrap=True)
        body.addWidget(self.status)
        row = QHBoxLayout()
        self.scan = QPushButton("扫描登录状态")
        self.scan.clicked.connect(self.accounts.scan)
        row.addWidget(self.scan)
        self.platform = QComboBox()
        for key, site in PLATFORMS.items():
            self.platform.addItem(site.label, key)
        chosen = window.current_platform()
        self.platform.setCurrentIndex(max(0, self.platform.findData(chosen)))
        row.addWidget(self.platform)
        login = QPushButton("打开网页登录")
        login.clicked.connect(self.open_login)
        row.addWidget(login)
        body.addLayout(row)
        layout.addWidget(account)
        preferences, body = panel()
        body.addWidget(text_label("软件更新", role="sectionTitle"))
        self.auto_update = QCheckBox("启动时自动检查更新")
        self.auto_update.setChecked(read_settings().get("auto_update", True) is not False)
        self.auto_update.toggled.connect(lambda enabled: save_settings(auto_update=enabled))
        body.addWidget(self.auto_update)
        layout.addWidget(preferences)
        layout.addStretch()
        row = QHBoxLayout()
        logs = QPushButton("诊断日志")
        logs.clicked.connect(window.show_logs)
        row.addWidget(logs)
        row.addStretch()
        close = QPushButton("完成")
        close.setObjectName("primary")
        close.setDefault(True)
        close.clicked.connect(self.close)
        row.addWidget(close)
        layout.addLayout(row)
        self.accounts.changed.connect(self.render)
        self.auto_login.toggled.connect(self.configure)
        self.source.currentIndexChanged.connect(self.configure)
        self.render()

    def render(self):
        self.status.setText(self.accounts.status)
        self.scan.setEnabled(self.accounts.process is None)
        selected = self.accounts.source_id
        self.source.blockSignals(True)
        self.source.clear()
        self.source.addItem("自动选择可用浏览器 / 程序网页登录", "")
        states = {"protected": "加密保护", "locked": "占用或无法打开", "empty": "无有效登录", "ready": "可读取", "partial": "部分可读取"}
        for item in self.accounts.sources:
            self.source.addItem(item["label"] + " · " + states.get(item["status"], item["status"]), item["id"])
        index = self.source.findData(selected)
        if selected and index < 0:
            self.source.addItem("原登录来源暂不可用，请重新扫描", selected)
            index = self.source.count() - 1
        self.source.setCurrentIndex(max(0, index))
        self.source.blockSignals(False)

    def configure(self, *_):
        self.accounts.configure(self.auto_login.isChecked(), self.source.currentData())

    def open_login(self):
        key = self.platform.currentData()
        url = None
        try:
            value, site, _ = download_link(self.window.url.text())
            if site.key == key:
                url = value
        except ValueError:
            pass
        try:
            self.accounts.open_login(key, url)
        except Exception as error:
            self.status.setText("网页登录组件未能打开：" + str(error))


class DownloadWindow(QMainWindow):
    def __init__(self, *, auto_scan=True, restore_web_login=True, check_updates=None,
                 store=None, command_factory=None, update_client_factory=None):
        super().__init__()
        self.setWindowTitle("视频下载器")
        self.setWindowIcon(QIcon(str(ROOT / "assets/app.ico")))
        self.resize(METRICS["default_width"], METRICS["default_height"])
        self.setMinimumSize(METRICS["min_width"], METRICS["min_height"])
        self.closing = self.install_exit = False
        self.output = output_dir()
        self.store = store or LibraryStore()
        self.search_dialog = None
        self.store.add_root(self.output)
        for old_root in read_settings().get("library_roots", []):
            if isinstance(old_root, str):
                self.store.add_root(old_root)
        self.logs = deque(maxlen=800)
        self.background = BackgroundPool(self, 1)
        self.accounts = AccountService(self)
        self.accounts.log.connect(self.add_log)
        manager_options = {"command_factory": command_factory} if command_factory else {}
        self.downloads = DownloadManager(self.store, self.accounts, self.output, self, **manager_options)
        self.downloads.log.connect(self.add_log)
        self.central = QWidget()
        self.central.setObjectName("windowRoot")
        shell = QHBoxLayout(self.central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        self.icon_rail = NavigationSidebar()
        self.icon_rail.page_requested.connect(self.set_page)
        self.icon_rail.search_requested.connect(self.show_search)
        self.icon_rail.settings_requested.connect(self.open_settings)
        self.icon_rail.open_requested.connect(self.open_media)
        self.menu_button = self.icon_rail.logo
        self.rail_navigation = self.icon_rail.navigation
        self.account_button = self.icon_rail.account_button
        self.navigation = []
        self.group = QActionGroup(self)
        self.group.setExclusive(True)
        for index, (title, image) in enumerate((("下载", "compose"), ("我的视频", "library-stack"), ("软件更新", "nav-update"))):
            action = QAction(icon(image, COLORS["text"]), title, self)
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, page=index: self.set_page(page))
            self.group.addAction(action)
            self.navigation.append(action)
        shell.addWidget(self.icon_rail)
        self.search_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self.search_shortcut.activated.connect(self.show_search)
        self.sidebar_shortcut = QShortcut(QKeySequence("Ctrl+B"), self)
        self.sidebar_shortcut.activated.connect(self.icon_rail.toggle)
        body_shell = QVBoxLayout()
        body_shell.setContentsMargins(0, 0, 0, 0)
        body_shell.setSpacing(0)
        page_header = QWidget()
        page_header.setFixedHeight(RAIL["header_height"])
        header = QHBoxLayout(page_header)
        header.setContentsMargins(METRICS["page_inset"], SPACE["xl"], METRICS["page_inset"], SPACE["xs"])
        self.page_title = text_label("", role="pageTitle")
        header.addWidget(self.page_title)
        header.addStretch()
        body_shell.addWidget(page_header)
        content = QVBoxLayout()
        content.setContentsMargins(METRICS["page_inset"], 0, METRICS["page_inset"], SPACE["page"])
        content.setSpacing(0)
        self.pages = QStackedWidget()
        self.download_page = DownloadPage()
        self.url = self.download_page.url
        self.download_page.submitted.connect(self.submit_link)
        self.pages.addWidget(self.download_page)
        self.library = LibraryPage(self.store, self.output)
        self.download_page.recent.itemDelegate().thumbnail_provider = self.library.model.thumbnail
        self.library.model.record_changed.connect(self.download_page.update_recent)
        self.library.open_requested.connect(self.open_media)
        self.download_page.open_requested.connect(self.open_media)
        self.library.download_requested.connect(lambda: self.set_page(0))
        self.library.output_changed.connect(self.choose_output)
        self.library.refreshed.connect(self.download_page.render_recent)
        self.library.refreshed.connect(self.icon_rail.set_rows)
        self.library.refreshed.connect(self.refresh_search)
        self.library.log.connect(self.add_log)
        self.pages.addWidget(self.library)
        self.update_page = UpdatePage()
        self.pages.addWidget(self.update_page)
        update_options = {"client_factory": update_client_factory} if update_client_factory else {}
        self.updater = UpdateController(self.update_page, self, **update_options)
        self.updater.navigate.connect(lambda: self.set_page(2))
        self.updater.available_changed.connect(self.update_available)
        self.updater.log.connect(self.add_log)
        content.addWidget(self.pages, 1)
        body_shell.addLayout(content, 1)
        shell.addLayout(body_shell, 1)
        self.setCentralWidget(self.central)
        self.setStyleSheet(stylesheet())
        self.downloads.changed.connect(self.render_task)
        self.downloads.rejected.connect(self.download_page.reject_input)
        self.downloads.duplicate.connect(self.already_downloaded)
        self.downloads.queue_changed.connect(self.render_queue)
        self.downloads.completed.connect(self.download_completed)
        self.download_page.cancel.connect(self.downloads.cancel_current)
        self.download_page.retry.connect(self.retry_download)
        self.download_page.login.connect(self.open_settings)
        self.download_page.show_library.connect(lambda: self.set_page(1))
        self.download_page.clear_queue.connect(self.downloads.clear_queue)
        self.set_page(0)
        self.download_page.render_recent(self.store.rows())
        self.icon_rail.set_rows(self.store.rows())
        self.last_result = None
        self.player_dialog = None
        self.settings_dialog = None
        self.stall_timer = QTimer(self)
        self.stall_timer.setInterval(1000)
        self.stall_timer.timeout.connect(self.update_stall)
        self.stall_timer.start()
        QTimer.singleShot(100, self.library.refresh)
        if auto_scan:
            QTimer.singleShot(350, self.accounts.scan)
        if restore_web_login and (data_dir() / "WebProfile").is_dir():
            QTimer.singleShot(250, self.restore_web)
        if (auto_scan if check_updates is None else check_updates) and read_settings().get("auto_update", True) is not False:
            QTimer.singleShot(750, lambda: self.updater.check(manual=False))
        self.close_timer = QTimer(self)
        self.close_timer.setInterval(100)
        self.close_timer.timeout.connect(self._finish_close)
        result_path = data_dir() / "updates/install-result.json"
        if result_path.is_file():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                self.update_page.status.setText(result.get("message", ""))
            except (OSError, ValueError):
                pass

    def set_page(self, page):
        self.pages.setCurrentIndex(page)
        self.navigation[page].setChecked(True)
        self.icon_rail.set_page(page)
        self.page_title.setText(("", "我的视频", "软件更新")[page])
        self.page_title.setVisible(page != 0)
        for index, name in enumerate(("compose", "library-stack", "nav-update")):
            self.navigation[index].setIcon(icon(name, COLORS["accent"] if index == page else COLORS["muted"]))
        if page == 0:
            self.url.setFocus(Qt.OtherFocusReason)
        elif page == 1:
            self.library.refresh()

    def show_search(self):
        if self.closing:
            return
        if self.search_dialog is None:
            self.search_dialog = MediaSearchDialog(self.store, self)
            self.search_dialog.open_requested.connect(self.open_media)
        self.search_dialog.refresh()
        self.search_dialog.show()
        self.search_dialog.raise_()
        self.search_dialog.activateWindow()
        self.search_dialog.search.setFocus(Qt.ShortcutFocusReason)
        self.search_dialog.search.selectAll()

    def refresh_search(self, rows):
        if self.search_dialog is not None:
            self.search_dialog.refresh(rows)

    def update_available(self, available):
        self.navigation[2].setText("软件更新 ●" if available else "软件更新")
        self.rail_navigation[2].setToolTip("软件更新 · 有新版本" if available else "软件更新")

    def submit_link(self, text):
        if self.closing or self.updater.installing:
            self.download_page.reject_input("正在准备更新，请等待新版启动后再下载。")
            return None
        self.download_page.input_message.hide()
        return self.downloads.submit(text)

    def render_task(self, task):
        # Queued completions should not replace a newer active task's feedback.
        if self.downloads.active and self.downloads.active is not task:
            return
        self.download_page.render(task)

    def render_queue(self):
        count = len(self.downloads.queue)
        self.download_page.queue_label.setText(f"等待 {count}" if count else "")
        self.download_page.queue_label.setVisible(bool(count))
        self.download_page.clear_queue_button.setVisible(bool(count))

    def download_completed(self, result):
        self.last_result = result
        self.library.reload()
        self.library.refresh()

    def already_downloaded(self, item):
        self.download_page.reject_input("这条作品已下载，可前往我的视频查看。")
        self.download_page.view_button.show()

    def retry_download(self):
        task = self.downloads.last
        if task:
            self.downloads.submit(task.url, force=True)

    def current_platform(self):
        try:
            return download_link(self.url.text())[1].key
        except ValueError:
            return self.downloads.last.platform.key if self.downloads.last else "bilibili"

    def open_settings(self):
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.raise_()
            return
        self.settings_dialog = SettingsDialog(self)
        self.settings_dialog.show()

    def restore_web(self):
        try:
            self.accounts.ensure_web()
        except Exception as error:
            self.add_log("网页登录恢复：" + str(error))

    def choose_output(self, folder):
        try:
            target = Path(folder).resolve()
            target.mkdir(parents=True, exist_ok=True)
            self.store.add_root(self.output)
            self.store.add_root(target)
            save_output(target)
            save_settings(library_roots=self.store.roots())
            self.output = target
            self.downloads.output = target
            self.library.set_output(target)
        except OSError as error:
            self.download_page.reject_input("无法保存目录设置：" + str(error))

    def open_media(self, item):
        if not Path(item["path"]).exists():
            QMessageBox.information(self, "文件不可用", "文件已被移动或删除，请刷新视频库，或在保存文件夹中确认位置。")
            self.library.refresh()
            return
        try:
            from media_player import GalleryDialog, PlayerDialog
            if self.player_dialog:
                try:
                    self.player_dialog.close()
                except RuntimeError:
                    pass
            self.player_dialog = GalleryDialog(item, self) if item["kind"] == "gallery" else PlayerDialog(item["path"], item["title"], self)
            self.player_dialog.show()
        except (ImportError, RuntimeError) as error:
            reply = QMessageBox.question(self, "内置播放不可用", "播放组件未能打开：" + str(error) + "\n是否使用 Windows 默认播放器？")
            if reply == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl.fromLocalFile(item["path"]))

    def add_log(self, text):
        self.logs.append(str(text))

    def show_logs(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("诊断日志")
        dialog.resize(760, 430)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(SPACE["xxl"], SPACE["xxl"], SPACE["xxl"], SPACE["xxl"])
        layout.setSpacing(SPACE["lg"])
        layout.addWidget(text_label("诊断日志", role="sectionTitle"))
        text = QPlainTextEdit("\n".join(self.logs))
        text.setPlaceholderText("暂无诊断日志。")
        text.setReadOnly(True)
        layout.addWidget(text, 1)
        done = QPushButton("完成")
        done.clicked.connect(dialog.close)
        layout.addWidget(done, 0, Qt.AlignRight)
        self.log_dialog = dialog
        dialog.show()

    def update_stall(self):
        import time
        task = self.downloads.active
        if task and time.monotonic() - task.updated > 2 and task.speed:
            task.speed = 0
            self.render_task(task)

    def closeEvent(self, event):
        if not self.closing:
            if not self.install_exit and (self.downloads.busy() or (self.updater.busy() and self.updater.mode == "downloading")):
                reply = QMessageBox.question(self, "任务进行中", "关闭窗口会取消未完成的任务。确定关闭？", QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
                if reply != QMessageBox.Yes:
                    event.ignore()
                    return
            self.closing = True
            self.downloads.shutdown()
            self.updater.shutdown()
            self.accounts.stop()
            self.library.shutdown()
            self.stall_timer.stop()
            if self.player_dialog:
                try:
                    self.player_dialog.close()
                except RuntimeError:
                    pass
        if self._jobs_running():
            self.page_title.setText("正在安全结束后台任务…")
            event.ignore()
            self.close_timer.start()
            return
        self.close_timer.stop()
        event.accept()

    def _jobs_running(self):
        return bool(self.downloads.active or self.updater.busy() or self.background.active
                    or self.library.pool.active or self.downloads.catalogue_jobs.active
                    or (self.accounts.process and self.accounts.process.state() != QProcess.NotRunning))

    def _finish_close(self):
        if not self._jobs_running():
            self.close_timer.stop()
            self.close()


def main():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    verification = "--verify-install" in sys.argv
    if verification:
        from desktop_verify import prepare_fonts
        prepare_fonts()
    # A per-user IPC server brings an existing v2 window forward without
    # monitoring the clipboard or starting a second copy of the same task.
    import hashlib
    server_name = "LocalVideoDownloader-" + hashlib.sha256(str(data_dir()).encode()).hexdigest()[:16]
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if socket.waitForConnected(200):
        socket.write(b"activate")
        socket.flush()
        socket.waitForBytesWritten(200)
        return 0
    QLocalServer.removeServer(server_name)
    server = QLocalServer()
    server.listen(server_name)
    try:
        window = DownloadWindow(auto_scan=not verification, restore_web_login=not verification)
    except Exception as error:
        QMessageBox.critical(None, "视频下载器未能启动", "无法读取本地视频库或配置，现有文件已保留。\n\n" + str(error))
        return 1

    def activate():
        connection = server.nextPendingConnection()
        connection.close()
        connection.deleteLater()
        window.showNormal()
        window.raise_()
        window.activateWindow()
    server.newConnection.connect(activate)
    window.show()
    if verification:
        from desktop_verify import verify
        verify(app, window, sys.argv[sys.argv.index("--verify-install") + 1])
    elif len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        window.url.setText(sys.argv[1])
        QTimer.singleShot(0, lambda: window.submit_link(sys.argv[1]))
    handshake = os.environ.get("VIDEO_DOWNLOADER_UPDATE_HANDSHAKE")
    nonce = os.environ.get("VIDEO_DOWNLOADER_UPDATE_NONCE")
    if handshake and nonce:
        from update_agent import write_json
        QTimer.singleShot(2000, lambda: write_json(handshake, {"version": APP_VERSION, "nonce": nonce, "pid": os.getpid(),
                              "page": window.pages.currentIndex(), "output": str(window.output), "library_count": len(window.store.rows())}))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
