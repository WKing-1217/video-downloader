"""Automatic Bilibili / Douyin / X downloader (Qt for Python)."""
import json
import os
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import QProcess, QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
    QFileDialog, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)
from platform_links import PLATFORMS, resolve_link
from runtime_paths import APP_DIR, FROZEN, output_dir, read_settings, save_output, save_settings, worker_command
from updater import UpdateController
from app_version import APP_VERSION

ROOT = Path(__file__).resolve().parent
OUTPUT = output_dir()
TOKENS = {"background": "#f5f6fa", "surface": "#ffffff", "text": "#202533",
          "muted": "#697386", "accent": "#dc4775", "border": "#e2e5ed"}
HEADER_METRICS = {"inset": 36, "top": 30, "gap": 14, "version_size": 16,
                  "update_size": 17, "button_padding_y": 10, "button_padding_x": 14}


def clock(seconds):
    seconds = round(float(seconds or 0))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class LoginSourceComboBox(QComboBox):
    """Keep page scrolling from accidentally changing the selected account."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("登录来源")

    def wheelEvent(self, event):
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


class DownloadWindow(QMainWindow):
    def __init__(self, *, auto_scan=True, restore_web_login=True, check_updates=None):
        super().__init__()
        self.setWindowTitle("视频下载器")
        self.setWindowIcon(QIcon(str(ROOT / "assets/app.ico")))
        self.resize(940, 840)
        self.setMinimumSize(760, 650)
        self.process = None
        self.buffer = b""
        self.result = None
        self.failed = False
        self.sources = []
        self.scan_process = None
        self.scan_buffer = b""
        self.web_login = None
        self.platform = None
        self.stderr = b""
        central = QWidget()
        central.setObjectName("windowRoot")
        shell = QVBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        self.header = QWidget()
        self.header.setObjectName("appHeader")
        header_row = QHBoxLayout(self.header)
        header_row.setContentsMargins(HEADER_METRICS["inset"], HEADER_METRICS["top"], HEADER_METRICS["inset"], 0)
        header_row.setSpacing(HEADER_METRICS["gap"])
        heading = QLabel("视频下载器")
        heading.setObjectName("heading")
        header_row.addWidget(heading)
        header_row.addStretch(1)
        self.current_version = QLabel("当前版本 v" + APP_VERSION)
        self.current_version.setObjectName("currentVersion")
        header_row.addWidget(self.current_version)
        self.update_button = QPushButton("检查更新")
        self.update_button.setObjectName("updateButton")
        self.update_button.setProperty("updateAvailable", False)
        header_row.addWidget(self.update_button)
        shell.addWidget(self.header)
        root = QWidget()
        root.setObjectName("content")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(root)
        self.scroll_area = scroll
        shell.addWidget(scroll, 1)
        self.setCentralWidget(central)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(HEADER_METRICS["inset"], 18, HEADER_METRICS["inset"], 28)
        layout.setSpacing(18)
        box = QFrame()
        box.setObjectName("card")
        form = QVBoxLayout(box)
        form.setContentsMargins(24, 22, 24, 22)
        form.setSpacing(14)
        form.addWidget(QLabel("视频链接"))
        row = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("链接粘贴处")
        self.url.setClearButtonEnabled(True)
        self.url.returnPressed.connect(self.start_download)
        row.addWidget(self.url, 1)
        self.paste = QPushButton("粘贴")
        self.paste.clicked.connect(lambda: self.url.setText(QApplication.clipboard().text().strip()))
        row.addWidget(self.paste)
        form.addLayout(row)
        self.platform_label = QLabel("支持哔哩哔哩、抖音、X（Twitter），无需切换平台")
        self.platform_label.setObjectName("muted")
        self.platform_label.setWordWrap(True)
        self.platform_label.hide()
        self.url.textChanged.connect(self.identify_platform)
        self.download = QPushButton("开始下载")
        self.download.setObjectName("primary")
        self.download.clicked.connect(self.start_download)
        form.addWidget(self.download)
        layout.addWidget(box)

        account_row = QHBoxLayout()
        self.account_label = QLabel("登录状态：下载时自动读取本机浏览器")
        self.account_label.setObjectName("muted")
        self.account_label.setWordWrap(True)
        account_row.addWidget(self.account_label, 1)
        self.scan_button = QPushButton("扫描登录状态")
        self.scan_button.clicked.connect(self.scan_browsers)
        account_row.addWidget(self.scan_button)
        self.login_button = QPushButton("网页登录")
        self.login_button.clicked.connect(self.open_web_login)
        account_row.addWidget(self.login_button)
        layout.addLayout(account_row)

        self.title = QLabel("等待一个好视频")
        self.title.setObjectName("taskTitle")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.status = QLabel("粘贴链接后点击「开始下载」。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.details = QLabel("视频与音频将自动合并为一个文件")
        self.details.setWordWrap(True)
        self.details.setObjectName("muted")
        layout.addWidget(self.details)

        actions = QHBoxLayout()
        self.open_file = QPushButton("播放视频")
        self.open_file.setEnabled(False)
        self.open_file.clicked.connect(self.play)
        actions.addWidget(self.open_file)
        folder = QPushButton("打开 video 文件夹")
        folder.clicked.connect(self.open_folder)
        actions.addWidget(folder)
        actions.addStretch()
        self.cancel = QPushButton("取消下载")
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(self.cancel_download)
        actions.addWidget(self.cancel)
        layout.addLayout(actions)

        self.advanced_toggle = QCheckBox("更多选项")
        self.advanced_toggle.toggled.connect(self.toggle_advanced)
        options_row = QHBoxLayout()
        options_row.addWidget(self.advanced_toggle)
        options_row.addStretch()
        layout.addLayout(options_row)
        self.advanced = QWidget()
        extra = QVBoxLayout(self.advanced)
        extra.setContentsMargins(0, 0, 0, 0)
        self.auto_login = QCheckBox("自动读取本机浏览器的登录状态")
        self.auto_login.setChecked(True)
        self.auto_login.toggled.connect(self.render_account_status)
        extra.addWidget(self.auto_login)
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("登录来源"))
        self.source_select = LoginSourceComboBox()
        self.source_select.addItem("自动选择已登录的浏览器", "")
        self.source_select.currentIndexChanged.connect(self.render_account_status)
        source_row.addWidget(self.source_select, 1)
        extra.addLayout(source_row)
        self.auto_update = QCheckBox("启动时检查更新")
        self.auto_update.setChecked(read_settings().get("auto_update", True) is not False)
        self.auto_update.toggled.connect(lambda enabled: save_settings(auto_update=enabled))
        extra.addWidget(self.auto_update)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(500)
        self.logs.setMaximumHeight(160)
        extra.addWidget(self.logs)
        self.advanced.hide()
        layout.addWidget(self.advanced)
        layout.addStretch(1)
        location = self.location = QLabel(f"保存位置：{OUTPUT}")
        location.setObjectName("muted")
        location.setWordWrap(True)
        location.setTextInteractionFlags(Qt.TextSelectableByMouse)
        destination_row = QHBoxLayout()
        destination_row.addWidget(location, 1)
        self.destination_button = QPushButton("更改位置")
        self.destination_button.clicked.connect(self.choose_output)
        destination_row.addWidget(self.destination_button)
        layout.addLayout(destination_row)
        self.setStyleSheet("""
            QWidget {color: %(text)s; font-family: 'Microsoft YaHei UI'; font-size: 17px;}
            QMainWindow, QScrollArea, QWidget#content, QWidget#windowRoot, QWidget#appHeader {background: %(background)s;}
            QLabel#heading {font-size: 30px; font-weight: 700;}
            QLabel#currentVersion {color: %(muted)s; font-size: %(version_size)spx;}
            QLabel#taskTitle {font-size: 22px; font-weight: 600;}
            QLabel#muted {color: %(muted)s; font-size: 15px;}
            QFrame#card {background: %(surface)s; border: 1px solid %(border)s; border-radius: 16px;}
            QFrame#card QLabel {background: transparent;}
            QLineEdit, QPlainTextEdit, QComboBox {background: white; border: 1px solid %(border)s;
                border-radius: 8px; padding: 12px; selection-background-color: %(accent)s;}
            QLineEdit:focus {border: 2px solid %(accent)s; padding: 11px;}
            QComboBox {padding-right: 48px;}
            QComboBox:focus {border-color: %(accent)s;}
            QComboBox::drop-down {subcontrol-origin: padding; subcontrol-position: top right;
                width: 44px; border: none; border-top-right-radius: 8px; border-bottom-right-radius: 8px;}
            QComboBox::drop-down:hover {background: #eef0f6;}
            QComboBox::down-arrow {image: url("%(chevron)s"); width: 18px; height: 18px;}
            QComboBox QAbstractItemView {background: %(surface)s; border: 1px solid %(border)s;
                selection-background-color: %(accent)s; selection-color: white; outline: none;}
            QPushButton {background: white; border: 1px solid %(border)s; border-radius: 8px;
                padding: 12px 18px; min-height: 22px;}
            QPushButton:hover {background: #eef0f6;}
            QPushButton:disabled {color: #a1a7b4; background: #eff0f4;}
            QPushButton#primary {background: %(accent)s; color: white; border: none; font-weight: 600;}
            QPushButton#primary:hover {background: #c83765;}
            QPushButton#primary:disabled {background: #c9a8b3;}
            QPushButton#updateButton {font-size: %(update_size)spx; padding: %(button_padding_y)spx %(button_padding_x)spx;}
            QPushButton#updateButton[updateAvailable="true"] {background: %(accent)s; color: white; border-color: %(accent)s; font-weight: 600;}
            QPushButton#updateButton[updateAvailable="true"]:hover {background: #c83765; border-color: #c83765;}
            QProgressBar {background: #e4e7ee; border: none; border-radius: 5px; height: 10px; max-height: 10px;}
            QProgressBar::chunk {background: %(accent)s; border-radius: 5px;}
            QCheckBox {spacing: 8px; font-size: 15px; color: %(muted)s;}
        """ % {**TOKENS, **HEADER_METRICS, "chevron": (ROOT / "assets/chevron-down.svg").as_posix()})
        for label in self.findChildren(QLabel):
            label.setTextFormat(Qt.PlainText)
        if auto_scan:
            QTimer.singleShot(300, self.scan_browsers)
        saved = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LocalVideoDownloader/WebProfile"
        if restore_web_login and saved.is_dir():
            QTimer.singleShot(100, self.ensure_web_login)
        self.updater = UpdateController(self)
        self.update_button.clicked.connect(lambda: self.updater.check(manual=True))
        if (auto_scan if check_updates is None else check_updates) and self.auto_update.isChecked():
            QTimer.singleShot(2000, lambda: self.auto_update.isChecked() and self.updater.check(manual=False))

    def toggle_advanced(self, visible):
        self.advanced.setVisible(visible)

    def identify_platform(self):
        try:
            _, self.platform = resolve_link(self.url.text())
            self.platform_label.setText(f"已识别：{self.platform.label} · 自动获取最高可用画质和音质")
        except ValueError:
            self.platform = None
            self.platform_label.setText("支持哔哩哔哩、抖音、X（Twitter），无需切换平台" if not self.url.text().strip()
                                        else "未识别到视频链接，请粘贴这三个平台的视频链接")
        self.render_account_status()

    def ensure_web_login(self):
        if self.web_login is None:
            from web_login import WebLogin
            self.web_login = WebLogin(self)
            self.web_login.changed.connect(self.render_account_status)
        return self.web_login

    def open_web_login(self):
        if not self.platform:
            self.account_label.setText("先粘贴视频链接，程序会自动打开对应平台的登录页面。")
            self.url.setFocus()
            return
        try:
            session = self.ensure_web_login()
            # Visiting the actual Douyin video also refreshes its browser challenge cookies.
            url = resolve_link(self.url.text())[0] if self.platform.key == "douyin" else None
            session.open(self.platform.key, url)
        except (ImportError, RuntimeError) as exc:
            self.account_label.setText("网页组件无法打开，请运行「安装依赖.bat」后重试。")
            self.logs.appendPlainText(str(exc))

    def render_account_status(self, *_):
        if not self.auto_login.isChecked():
            self.account_label.setText("登录状态：未启用自动读取")
            return
        key = self.platform.key if self.platform else None
        selected = self.source_select.currentData()
        browser_logged = any(s.get("sites", {}).get(key, {}).get("login_found") for s in self.sources)
        if key and not selected and self.web_login and self.web_login.for_platform(key) and (
                self.web_login.has_login(key) or not browser_logged):
            self.account_label.setText(f"登录状态：已读取程序内的 {self.platform.label} 网页信息")
            return
        sources = [s for s in self.sources if not selected or s["id"] == selected]
        keys = [key] if key else list(PLATFORMS)
        logged = [(s, k) for s in sources for k in keys
                  if s.get("sites", {}).get(k, {}).get("login_found")]
        if logged:
            item, site = logged[0]
            self.account_label.setText(f"已发现 {PLATFORMS[site].label} 登录信息 · {item['label']}")
        elif any(s.get("sites", {}).get(k, {}).get("cookies") for s in sources for k in keys):
            self.account_label.setText("已读取网页访问信息，未检测到账号登录")
        elif any(s["status"] in {"protected", "locked"} for s in sources):
            self.account_label.setText("登录信息受浏览器保护或占用，可点「网页登录」")
        elif self.sources:
            self.account_label.setText("未找到可用登录信息，可点「网页登录」")
        else:
            self.account_label.setText("登录状态：下载时自动读取本机浏览器")

    def scan_browsers(self):
        if self.scan_process and self.scan_process.state() != QProcess.NotRunning:
            return
        self.scan_buffer = b""
        self.scan_button.setEnabled(False)
        self.account_label.setText("正在扫描本机浏览器的登录状态…")
        self.scan_process = QProcess(self)
        self.scan_process.setWorkingDirectory(str(APP_DIR))
        self.scan_process.readyReadStandardOutput.connect(self.read_scan_output)
        self.scan_process.finished.connect(self.scan_finished)
        self.scan_process.errorOccurred.connect(self.scan_error)
        executable, args = worker_command(["--scan-browsers"])
        self.scan_process.start(executable, args)

    def scan_error(self, error):
        if error == QProcess.FailedToStart:
            self.account_label.setText("扫描服务未能启动，请重新安装视频下载器。")
            self.scan_button.setEnabled(True)

    def read_scan_output(self):
        self.scan_buffer += bytes(self.scan_process.readAllStandardOutput())
        while b"\n" in self.scan_buffer:
            line, self.scan_buffer = self.scan_buffer.split(b"\n", 1)
            try:
                event = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if event.get("event") == "scan_progress":
                self.account_label.setText(event["message"])
            elif event.get("event") == "accounts":
                self.update_accounts(event["sources"])
            elif event.get("event") == "error":
                self.logs.appendPlainText(event["message"])

    def update_accounts(self, sources, platform=None):
        if platform:
            previous = {s["id"]: s for s in self.sources}
            for item in sources:
                old = previous.get(item["id"], {}).get("sites", {})
                item["sites"] = {**old, **item.get("sites", {})}
        self.sources = sources
        previous = self.source_select.currentData()
        self.source_select.blockSignals(True)
        self.source_select.clear()
        self.source_select.addItem("自动选择已登录的浏览器 / 程序网页登录", "")
        states = {"ready": "可读取", "partial": "部分可读取", "protected": "加密保护",
                  "locked": "无法打开", "empty": "无有效信息", "unreadable": "读取失败"}
        for item in sources:
            self.source_select.addItem(f"{item['label']} · {states.get(item['status'], item['status'])}", item["id"])
            self.logs.appendPlainText(f"{item['label']}：{item['message']}")
        index = self.source_select.findData(previous)
        self.source_select.setCurrentIndex(max(0, index))
        self.source_select.blockSignals(False)
        self.render_account_status()

    def scan_finished(self, code, _):
        self.read_scan_output()
        self.scan_button.setEnabled(not self.process or self.process.state() == QProcess.NotRunning)
        if code:
            self.account_label.setText("扫描失败，可展开运行日志查看详情。")
            self.logs.appendPlainText(bytes(self.scan_process.readAllStandardError()).decode("utf-8", errors="replace"))
        else:
            self.render_account_status()

    @staticmethod
    def python_executable():
        executable = Path(sys.executable)
        return executable.with_name("python.exe") if executable.name.lower() == "pythonw.exe" else executable

    def set_busy(self, busy):
        for control in (self.url, self.paste, self.download, self.source_select, self.auto_login, self.login_button, self.destination_button):
            control.setEnabled(not busy)
        self.scan_button.setEnabled(not busy and (not self.scan_process or self.scan_process.state() == QProcess.NotRunning))
        self.cancel.setEnabled(busy)

    def start_download(self):
        if self.process and self.process.state() != QProcess.NotRunning:
            return
        if not self.url.text().strip():
            self.status.setText("先粘贴一个视频链接。")
            self.url.setFocus()
            return
        try:
            url, platform = resolve_link(self.url.text())
        except ValueError as exc:
            self.status.setText(str(exc))
            self.url.setFocus()
            return
        self.result = None
        self.failed = False
        self.buffer = b""
        self.stderr = b""
        self.logs.clear()
        self.open_file.setText("播放视频")
        self.open_file.setEnabled(False)
        self.set_busy(True)
        self.title.setText("正在读取作品信息")
        self.status.setText(f"连接 {platform.label}，自动选择画质和音质…")
        self.details.setText("开始下载后显示实时进度")
        self.progress.setRange(0, 0)
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(APP_DIR))
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.readyReadStandardError.connect(self.read_errors)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        args = [url]
        snapshot = []
        if not self.auto_login.isChecked():
            args.append("--no-browser-cookies")
        elif self.source_select.currentData():
            args += ["--browser-source", self.source_select.currentData()]
        elif self.web_login:
            snapshot = self.web_login.for_platform(platform.key)
        if snapshot:
            args.append("--session-stdin")
            self.process.started.connect(lambda: self.send_web_session(snapshot))
        executable, args = worker_command(args)
        self.process.start(executable, args)

    def send_web_session(self, snapshot):
        payload = {"cookies": snapshot, "user_agent": self.web_login.profile.httpUserAgent()}
        self.process.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        self.process.closeWriteChannel()

    def read_errors(self):
        data = bytes(self.process.readAllStandardError())
        self.stderr += data
        self.logs.appendPlainText(data.decode("utf-8", errors="replace"))

    def read_output(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            self.consume_line(line)

    def consume_line(self, line):
        try:
            event = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeError):
            self.logs.appendPlainText(line.decode("utf-8", errors="replace"))
            return
        kind = event.get("event")
        if kind == "platform":
            self.platform_label.setText(f"已识别：{event['label']} · 自动获取最高可用画质和音质")
        elif kind == "accounts":
            self.update_accounts(event["sources"], event.get("platform"))
        elif kind == "login_source":
            self.account_label.setText(event["message"])
        elif kind == "metadata":
            self.title.setText(event["title"])
            if event.get("content_type") == "gallery":
                self.details.setText(f"图文作品 · {event['image_count']} 张图片 · "
                                     f"{event['live_photo_count']} 段实况 · 正在保存原始文件")
            else:
                self.details.setText(f"原片时长 {clock(event['duration'])} · 正在下载最高可用画质和音质")
        elif kind == "stage":
            self.status.setText(event["message"])
            self.progress.setRange(0, 0)
        elif kind == "log":
            self.logs.appendPlainText(event.get("message", ""))
        elif kind == "progress":
            total = event.get("total") or 0
            downloaded = event.get("downloaded") or 0
            self.progress.setRange(0, 100 if total else 0)
            if total:
                self.progress.setValue(min(100, round(downloaded * 100 / total)))
            percent = f"{downloaded / total:.0%}" if total else "计算大小中"
            self.status.setText(f"正在下载视频 / 音频 · {percent}")
            speed = (event.get("speed") or 0) / 1024 / 1024
            eta = event.get("eta")
            self.details.setText(f"{downloaded / 1024 / 1024:.1f} MB · {speed:.1f} MB/s" +
                                 (f" · 剩余约 {clock(eta)}" if eta is not None else ""))
        elif kind == "error":
            self.failed = True
            self.status.setText("下载失败：" + event["message"])
            self.logs.appendPlainText(event["message"])
        elif kind == "complete":
            self.result = event
            self.title.setText(event["title"])
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
            if event.get("content_type") == "gallery":
                self.status.setText("导出完成 · 图片、实况和配乐已逐项检查")
                self.details.setText(f"{event['image_count']} 张图片 · {event['live_photo_count']} 段实况 · "
                                     f"{event['music_count']} 首配乐 · {event['size'] / 1024 / 1024:.1f} MB")
                self.open_file.setText("查看作品文件夹")
            else:
                self.status.setText("下载完成 · 视频、音频和完整时长已检查")
                audio = f"{event['audio_codec'].upper()} 音频"
                if event.get("audio_bitrate"):
                    audio += f" {event['audio_bitrate'] / 1000:.0f} kb/s"
                self.details.setText(f"{event['width']} × {event['height']} · {clock(event['duration'])} · "
                                     f"{audio} · {event['size'] / 1024 / 1024:.1f} MB")
                self.open_file.setText("播放视频")
            self.open_file.setEnabled(True)

    def process_error(self, error):
        if error == QProcess.FailedToStart:
            self.failed = True
            self.status.setText("下载服务未能启动，请重新安装视频下载器后重试。")
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.set_busy(False)

    def finished(self, code, exit_status):
        self.read_output()
        self.read_errors()
        if self.buffer.strip():
            self.consume_line(self.buffer)
            self.buffer = b""
        self.set_busy(False)
        self.download.setText("再下载一个" if self.result else "重新下载")
        if not self.result:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            if not self.failed:
                self.status.setText(f"下载进程已退出（{code}），可展开运行日志查看详情。")
            self.details.setText("链接已保留，可重试；需要登录时点击「扫描登录状态」或「网页登录」。")

    def stop_process(self):
        if self.process and self.process.state() != QProcess.NotRunning:
            pid = self.process.processId()
            if os.name == "nt":
                try:
                    stopped = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                             creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, timeout=10)
                    if stopped.returncode:
                        self.process.kill()
                except (OSError, subprocess.TimeoutExpired):
                    self.process.kill()
            else:
                self.process.kill()
            self.process.waitForFinished(3000)

    def cancel_download(self):
        self.failed = True
        self.stop_process()
        self.status.setText("已取消下载；重新下载会尽量续传。")

    def play(self):
        if self.result:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.result["path"]))

    def open_folder(self):
        OUTPUT.mkdir(exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(OUTPUT)))

    def choose_output(self):
        global OUTPUT
        folder = QFileDialog.getExistingDirectory(self, "选择视频保存位置", str(OUTPUT))
        if folder:
            OUTPUT = Path(folder)
            save_output(folder)
            # The development worker also receives the chosen destination.
            os.environ["VIDEO_DOWNLOADER_OUTPUT"] = str(OUTPUT)
            self.location.setText(f"保存位置：{OUTPUT}")

    def closeEvent(self, event):
        if self.process and self.process.state() != QProcess.NotRunning:
            answer = QMessageBox.question(self, "下载进行中", "关闭窗口会取消当前下载，确定关闭？")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.stop_process()
        if self.scan_process and self.scan_process.state() != QProcess.NotRunning:
            self.scan_process.kill()
            self.scan_process.waitForFinished(2000)
        if self.web_login:
            self.web_login.close()
        if not self.updater.stop():
            event.ignore()
            QTimer.singleShot(500, self.close)
            return
        event.accept()


def main():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    verification = "--verify-install" in sys.argv
    if verification:
        from desktop_verify import prepare_fonts
        prepare_fonts()
    app.setFont(QFont("Microsoft YaHei UI", 12))
    window = DownloadWindow(auto_scan=not verification, restore_web_login=not verification)
    if len(sys.argv) > 1:
        window.url.setText(sys.argv[1])
    window.show()
    if verification:
        from desktop_verify import verify
        verify(app, window, sys.argv[sys.argv.index("--verify-install") + 1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
