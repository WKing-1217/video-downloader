"""Windows v2: paste downloads, a local media library, and an update workbench."""
from collections import deque
import json
import os
from pathlib import Path
import sys

from PySide6.QtCore import QProcess, QTimer, Qt, QUrl, Signal, QSize
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
    QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QStackedWidget, QToolButton, QVBoxLayout, QWidget, QFrame)

from app_version import APP_VERSION
from async_jobs import BackgroundPool
from download_service import AccountService, DownloadManager
from library_page import LibraryPage
from media_library import LibraryStore
from platform_links import PLATFORMS, download_link
from runtime_paths import APP_DIR, FROZEN, data_dir, output_dir, read_settings, save_output, save_settings
from ui_theme import METRICS, ROOT, icon, stylesheet
from ui_widgets import LoginSourceComboBox, PasteLinkEdit, clock_text, panel, size_text, text_label
from updater import UpdateController, UpdatePage


class DownloadPage(QWidget):
    show_library = Signal()
    retry = Signal()
    login = Signal()
    cancel = Signal()
    clear_queue = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        entry, body = panel()
        body.addWidget(text_label("粘贴视频链接，自动开始下载", role="sectionTitle"))
        row = QHBoxLayout()
        self.url = PasteLinkEdit()
        self.url.setObjectName("linkInput")
        self.url.setPlaceholderText("链接粘贴处")
        self.url.setClearButtonEnabled(True)
        self.url.setAccessibleName("视频链接，主动粘贴后自动下载")
        row.addWidget(self.url, 1)
        self.paste = QPushButton("粘贴")
        self.paste.clicked.connect(self.url.paste)
        row.addWidget(self.paste)
        body.addLayout(row)
        body.addWidget(text_label("支持 Bilibili、抖音、X。手动输入链接后可按 Enter。", role="muted", wrap=True))
        self.input_message = text_label("", role="error", wrap=True)
        self.input_message.hide()
        body.addWidget(self.input_message)
        layout.addWidget(entry)
        task, body = panel()
        self.task_title = text_label("等待粘贴链接", role="sectionTitle", wrap=True)
        body.addWidget(self.task_title)
        self.task_status = text_label("下载任务会在这里显示，完成后自动加入视频库。", wrap=True)
        body.addWidget(self.task_status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        body.addWidget(self.progress)
        self.details = text_label("", role="muted", wrap=True)
        self.details.hide()
        body.addWidget(self.details)
        actions = QHBoxLayout()
        self.cancel_button = QPushButton("取消当前下载")
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.hide()
        actions.addWidget(self.cancel_button)
        self.retry_button = QPushButton("重试")
        self.retry_button.clicked.connect(self.retry)
        self.retry_button.hide()
        actions.addWidget(self.retry_button)
        self.login_button = QPushButton("网页登录")
        self.login_button.clicked.connect(self.login)
        self.login_button.hide()
        actions.addWidget(self.login_button)
        self.view_button = QPushButton("前往我的视频")
        self.view_button.setObjectName("link")
        self.view_button.clicked.connect(self.show_library)
        self.view_button.hide()
        actions.addWidget(self.view_button)
        actions.addStretch()
        body.addLayout(actions)
        self.queue_label = text_label("", role="muted")
        self.queue_label.hide()
        body.addWidget(self.queue_label)
        self.clear_queue_button = QPushButton("清空等待任务")
        self.clear_queue_button.clicked.connect(self.clear_queue)
        self.clear_queue_button.hide()
        body.addWidget(self.clear_queue_button, 0, Qt.AlignLeft)
        layout.addWidget(task)
        recent = QHBoxLayout()
        recent.addWidget(text_label("最近下载", role="sectionTitle"))
        recent.addStretch()
        more = QPushButton("查看全部")
        more.setObjectName("link")
        more.clicked.connect(self.show_library)
        recent.addWidget(more)
        layout.addLayout(recent)
        self.recent = QListWidget()
        self.recent.setMaximumHeight(140)
        self.recent.setStyleSheet("QListWidget {background: transparent; border: none;} QListWidget::item {padding: 8px 2px;}")
        self.recent.itemClicked.connect(lambda _: self.show_library.emit())
        layout.addWidget(self.recent)
        layout.addStretch(1)

    def reject_input(self, message):
        self.input_message.setText(message)
        self.input_message.show()

    def render(self, task):
        self.task_title.setText(task.title)
        self.task_status.setText(task.message)
        active = task.state in {"running", "saving"}
        self.cancel_button.setVisible(task.state == "running")
        self.cancel_button.setEnabled(not task.cancelled)
        self.retry_button.setVisible(task.state in {"failed", "cancelled"})
        self.login_button.setVisible(task.state == "failed")
        self.view_button.setVisible(task.state == "done")
        if active and not task.total:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(100 if task.state == "done" else min(100, round(task.downloaded * 100 / task.total)) if task.total else 0)
        if task.state == "done" and task.result:
            result = task.result
            self.details.setText((clock_text(result.get("duration")) + " · " if result.get("duration") else "图文作品 · ") + size_text(result["size"]))
        elif task.total:
            self.details.setText(f"{size_text(task.downloaded)} / {size_text(task.total)} · {task.downloaded / task.total:.0%} · {task.speed / 1024 ** 2:.1f} MB/s"
                                 + (" · 剩余 " + clock_text(task.eta) if task.eta is not None else ""))
        else:
            self.details.setText("")
        self.details.setVisible(bool(self.details.text()))

    def render_recent(self, rows):
        self.recent.clear()
        for item in rows[:3]:
            self.recent.addItem(item["title"] + "   ·   " + size_text(item["size"]))
        if not rows:
            self.recent.addItem("还没有下载记录")


class SettingsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.accounts = window, window.accounts
        self.setWindowTitle("登录与更多选项")
        self.resize(620, 370)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)
        self.auto_login = QCheckBox("自动读取本机浏览器的登录状态")
        self.auto_login.setChecked(self.accounts.auto_login)
        layout.addWidget(self.auto_login)
        row = QHBoxLayout()
        row.addWidget(text_label("登录来源"))
        self.source = LoginSourceComboBox()
        row.addWidget(self.source, 1)
        layout.addLayout(row)
        self.status = text_label(self.accounts.status, role="muted", wrap=True)
        layout.addWidget(self.status)
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
        layout.addLayout(row)
        layout.addWidget(text_label("网页登录使用程序自己的登录窗口，不会修改浏览器安全设置。", role="muted", wrap=True))
        self.auto_update = QCheckBox("启动时自动检查更新")
        self.auto_update.setChecked(read_settings().get("auto_update", True) is not False)
        self.auto_update.toggled.connect(lambda enabled: save_settings(auto_update=enabled))
        layout.addWidget(self.auto_update)
        row = QHBoxLayout()
        logs = QPushButton("诊断日志")
        logs.clicked.connect(window.show_logs)
        row.addWidget(logs)
        row.addStretch()
        close = QPushButton("完成")
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
        self.resize(1050, 720)
        self.setMinimumSize(860, 620)
        self.closing = self.install_exit = False
        self.output = output_dir()
        self.store = store or LibraryStore()
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
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(METRICS["sidebar"])
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(12, 22, 12, 20)
        nav.setSpacing(9)
        brand = text_label("视频下载器", role="brand")
        nav.addWidget(brand, 0, Qt.AlignHCenter)
        nav.addSpacing(22)
        self.navigation = []
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for index, (title, image) in enumerate((("下载", "nav-download"), ("我的视频", "nav-library"), ("软件更新", "nav-update"))):
            button = QPushButton(icon(image), title)
            button.setObjectName("nav")
            button.setIconSize(QSize(20, 20))
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, page=index: self.set_page(page))
            self.group.addButton(button, index)
            self.navigation.append(button)
            nav.addWidget(button)
        nav.addStretch(1)
        self.version = text_label("v" + APP_VERSION, role="muted")
        nav.addWidget(self.version, 0, Qt.AlignHCenter)
        shell.addWidget(sidebar)
        content = QVBoxLayout()
        content.setContentsMargins(METRICS["page_inset"], 22, METRICS["page_inset"], 22)
        content.setSpacing(20)
        header = QHBoxLayout()
        self.page_title = text_label("视频下载", role="pageTitle")
        header.addWidget(self.page_title)
        header.addStretch()
        self.settings_button = QToolButton()
        self.settings_button.setIcon(icon("settings"))
        self.settings_button.setIconSize(QSize(19, 19))
        self.settings_button.setToolTip("登录、保存位置与更多选项")
        self.settings_button.setAccessibleName("设置")
        self.settings_button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.settings_button)
        menu.addAction("登录与更多选项", self.open_settings)
        menu.addAction("打开保存文件夹", lambda: self.library.open_folder())
        menu.addAction("更改保存位置", lambda: self.library.choose_output())
        menu.addAction("诊断日志", self.show_logs)
        self.settings_button.setMenu(menu)
        header.addWidget(self.settings_button)
        content.addLayout(header)
        self.pages = QStackedWidget()
        self.download_page = DownloadPage()
        self.url = self.download_page.url
        self.url.pasted.connect(self.submit_link)
        self.url.returnPressed.connect(lambda: self.submit_link(self.url.text()))
        self.pages.addWidget(self.download_page)
        self.library = LibraryPage(self.store, self.output)
        self.library.open_requested.connect(self.open_media)
        self.library.output_changed.connect(self.choose_output)
        self.library.refreshed.connect(self.download_page.render_recent)
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
        shell.addLayout(content, 1)
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
        self.page_title.setText(("视频下载", "我的视频", "软件更新")[page])
        if page == 1:
            self.library.refresh()

    def update_available(self, available):
        self.navigation[2].setText("软件更新 ●" if available else "软件更新")

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
        self.download_page.queue_label.setText(f"还有 {count} 个链接等待下载" if count else "")
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
        text = QPlainTextEdit("\n".join(self.logs))
        text.setReadOnly(True)
        layout.addWidget(text)
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
