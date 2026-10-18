"""Qt update UI: background checks, explicit downloads and installer handoff."""
import os
import hashlib
from pathlib import Path
import threading

from PySide6.QtCore import QObject, QProcess, QThread, QTimer, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout

from app_version import APP_VERSION
from runtime_paths import APP_DIR, FROZEN
from update_core import UpdateCancelled, UpdateClient, UpdateError


class UpdateJob(QThread):
    checked = Signal(object)
    downloaded = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, *, info=None, client_factory=UpdateClient):
        super().__init__()
        self.info = info
        self.client_factory = client_factory
        self.cancelled = threading.Event()

    def run(self):
        client = self.client_factory(cancelled=self.cancelled)
        try:
            if self.info is None:
                self.checked.emit(client.check())
            else:
                cache = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LocalVideoDownloader/updates"
                self.downloaded.emit(client.download(self.info, cache, self.progress.emit))
        except UpdateCancelled:
            pass
        except UpdateError as error:
            self.failed.emit(str(error))
        except Exception:
            self.failed.emit("暂时无法检查更新，请稍后重试。")
        finally:
            client.close()


class UpdateController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.jobs = []
        self.info = None
        self.installer = None
        self.dialog = None

    def refresh_button(self, *, checking=False):
        button = self.window.update_button
        available = bool(self.info and self.info.available)
        button.setText("正在检查…" if checking else f"发现新版本 v{self.info.version}" if available else "检查更新")
        button.setProperty("updateAvailable", available)
        button.setToolTip(f"当前版本 v{APP_VERSION}" + (f"，可更新至 v{self.info.version}" if available else ""))
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def check(self, *, manual=False):
        if any(job.isRunning() for job in self.jobs):
            return
        self.refresh_button(checking=True)
        self.window.update_button.setEnabled(False)
        job = UpdateJob()
        self.jobs.append(job)
        job.checked.connect(lambda info: self.checked(info, manual))
        job.failed.connect(lambda message: self.error(message, manual))
        job.finished.connect(lambda: self.job_finished(job))
        job.start()

    def job_finished(self, job):
        self.window.update_button.setEnabled(True)
        self.refresh_button()
        if job in self.jobs:
            self.jobs.remove(job)
        job.deleteLater()

    def checked(self, info, manual):
        if not self.info or self.info.version != info.version:
            self.installer = None
        self.info = info
        self.refresh_button()
        if info.available:
            self.window.logs.appendPlainText("发现新版本 " + info.version + "，可点击「发现新版本」更新。")
        if manual:
            self.show_dialog()

    def error(self, message, manual):
        self.window.logs.appendPlainText("更新：" + message)
        if manual:
            self.info = None
            self.show_dialog(message)

    def show_dialog(self, error=None):
        if self.dialog and self.dialog.isVisible():
            self.dialog.raise_()
            return
        self.dialog = dialog = QDialog(self.window)
        dialog.setWindowTitle("软件更新")
        dialog.setModal(True)
        dialog.resize(520, 300)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)
        available = bool(self.info and self.info.available)
        self.message = QLabel(error or (f"发现新版本 {self.info.version}" if available else "已经是最新版本"))
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        layout.addWidget(QLabel("当前版本 " + APP_VERSION))
        if available and self.info.notes:
            notes = QPlainTextEdit(self.info.notes)
            notes.setReadOnly(True)
            notes.setMaximumHeight(130)
            layout.addWidget(notes)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setVisible(False)
        layout.addWidget(self.bar)
        buttons = QHBoxLayout()
        buttons.addStretch()
        close = QPushButton("关闭")
        close.clicked.connect(dialog.close)
        buttons.addWidget(close)
        self.action = QPushButton("安装更新" if self.installer else "下载更新")
        self.action.setVisible(available)
        self.action.clicked.connect(self.install if self.installer else self.download)
        buttons.addWidget(self.action)
        layout.addLayout(buttons)
        dialog.show()

    def download(self):
        if not self.info or any(job.isRunning() for job in self.jobs):
            return
        self.action.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setValue(0)
        self.message.setText("正在下载更新…")
        job = UpdateJob(info=self.info)
        self.jobs.append(job)
        job.progress.connect(self.download_progress)
        job.downloaded.connect(self.ready)
        job.failed.connect(self.download_error)
        job.finished.connect(lambda: self.job_finished(job))
        job.start()

    def download_progress(self, done, total):
        self.bar.setValue(round(done / total * 100))

    def download_error(self, message):
        self.message.setText(message)
        self.action.setEnabled(True)
        self.action.setText("重新检查")
        self.action.clicked.disconnect()
        self.action.clicked.connect(self.retry_check)

    def retry_check(self):
        self.dialog.close()
        self.info = self.installer = None
        self.check(manual=True)

    def ready(self, installer):
        self.installer = installer
        self.message.setText("更新包已下载并通过校验。安装时会关闭当前窗口。")
        self.action.setText("安装更新")
        self.action.setEnabled(True)
        self.action.clicked.disconnect()
        self.action.clicked.connect(self.install)

    def install(self):
        if self.window.process and self.window.process.state() != QProcess.NotRunning:
            self.message.setText("请先完成或取消当前视频下载，再安装更新。")
            return
        if not self.installer or not Path(self.installer).is_file():
            return
        with Path(self.installer).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != self.info.sha256:
                self.message.setText("更新包已改变，请重新下载。")
                self.installer = None
                self.action.setText("下载更新")
                self.action.clicked.disconnect()
                self.action.clicked.connect(self.download)
                return
        arguments = ["/CLOSEAPPLICATIONS", "/NORESTART"]
        if FROZEN:
            arguments.append("/DIR=" + str(APP_DIR))
        started, _pid = QProcess.startDetached(str(self.installer), arguments)
        if started:
            QTimer.singleShot(0, self.window.close)
        else:
            self.message.setText("无法启动安装程序，请重新下载更新。")

    def stop(self):
        for job in list(self.jobs):
            job.cancelled.set()
        for job in list(self.jobs):
            if not job.wait(8500):
                return False
        return True
