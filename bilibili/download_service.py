"""Queued QProcess downloads and unchanged site-scoped browser authentication."""
from collections import deque
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal
from async_jobs import BackgroundPool
from platform_links import PLATFORMS, download_link
from runtime_paths import APP_DIR, data_dir, read_settings, save_settings, worker_command


class AccountService(QObject):
    changed = Signal()
    log = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        saved = read_settings()
        self.auto_login = saved.get("auto_login", True) is not False
        self.source_id = str(saved.get("browser_source") or "")
        self.sources = []
        self.status = "下载时自动读取可用的浏览器登录状态"
        self.process = None
        self.web = None

    def configure(self, auto_login, source_id):
        self.auto_login, self.source_id = bool(auto_login), source_id or ""
        save_settings(auto_login=self.auto_login, browser_source=self.source_id)
        self.changed.emit()

    def accept_sources(self, sources, platform=None):
        if platform:
            previous = {item["id"]: item for item in self.sources}
            for item in sources:
                item["sites"] = {**previous.get(item["id"], {}).get("sites", {}), **item.get("sites", {})}
        self.sources = sources
        logged = [item for item in sources if any(site.get("login_found") for site in item.get("sites", {}).values())]
        if logged:
            self.status = "已发现可用登录信息 · " + logged[0]["label"]
        elif any(item["status"] in {"protected", "locked"} for item in sources):
            self.status = "部分浏览器登录信息受保护或占用，可使用程序内网页登录。"
        else:
            self.status = "未发现有效账号登录，可直接尝试下载公开作品。"
        for item in sources:
            self.log.emit(f"{item['label']}：{item['message']}")
        self.changed.emit()

    def scan(self):
        if self.process and self.process.state() != QProcess.NotRunning:
            return
        self.status = "正在扫描本机浏览器的登录状态…"
        self.changed.emit()
        process = self.process = QProcess(self)
        process._buffer = b""
        process.setWorkingDirectory(str(APP_DIR))
        process.readyReadStandardOutput.connect(lambda: self._read(process))
        process.finished.connect(lambda code, status: self._finished(process, code))
        process.errorOccurred.connect(lambda error: self._error(process, error))
        executable, args = worker_command(["--scan-browsers"])
        process.start(executable, args)

    def _read(self, process):
        process._buffer += bytes(process.readAllStandardOutput())
        while b"\n" in process._buffer:
            line, process._buffer = process._buffer.split(b"\n", 1)
            try:
                event = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if event.get("event") == "accounts":
                self.accept_sources(event["sources"])
            elif event.get("event") == "scan_progress":
                self.status = event["message"]
                self.changed.emit()

    def _error(self, process, error):
        if error == QProcess.FailedToStart:
            self.status = "扫描服务未启动，请检查安装是否完整。"
            self.process = None
            self.changed.emit()
            process.deleteLater()

    def _finished(self, process, code):
        self._read(process)
        if code:
            self.status = "扫描失败，可使用网页登录；详情见诊断日志。"
            self.log.emit(bytes(process.readAllStandardError()).decode("utf-8", errors="replace")[-3000:])
        if self.process is process:
            self.process = None
        self.changed.emit()
        process.deleteLater()

    def ensure_web(self):
        if self.web is None:
            from web_login import WebLogin
            self.web = WebLogin(self)
            self.web.changed.connect(self.changed)
        return self.web

    def open_login(self, platform_key, url=None):
        self.ensure_web().open(platform_key, url if platform_key == "douyin" else None)

    def arguments(self, platform):
        if not self.auto_login:
            return ["--no-browser-cookies"], None
        if self.source_id:
            return ["--browser-source", self.source_id], None
        if self.web:
            snapshot = self.web.for_platform(platform.key)
            if snapshot:
                return ["--session-stdin"], {"cookies": snapshot, "user_agent": self.web.profile.httpUserAgent()}
        return [], None

    def stop(self):
        if self.process and self.process.state() != QProcess.NotRunning:
            self.process.kill()
        if self.web:
            self.web.close()


@dataclass
class DownloadTask:
    url: str
    platform: object
    key: str
    output: Path
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    title: str = "正在解析作品"
    state: str = "queued"
    message: str = "等待下载"
    downloaded: int = 0
    total: int = 0
    speed: float = 0
    eta: float | None = None
    updated: float = field(default_factory=time.monotonic)
    result: dict | None = None
    error: str = ""
    cancelled: bool = False


class DownloadManager(QObject):
    changed = Signal(object)
    completed = Signal(object)
    duplicate = Signal(object)
    rejected = Signal(str)
    log = Signal(str)
    queue_changed = Signal()
    idle = Signal()

    def __init__(self, store, accounts, output, parent=None, command_factory=worker_command):
        super().__init__(parent)
        self.store, self.accounts, self.output = store, accounts, Path(output)
        self.command_factory = command_factory
        self.queue = deque()
        self.active = None
        self.last = None
        self.process = None
        self.closing = False
        self.catalogue_jobs = BackgroundPool(self, 1)
        self.pending_keys = set()

    def busy(self):
        return bool(self.active or self.queue or self.catalogue_jobs.active)

    def submit(self, text, *, force=False):
        try:
            url, platform, key = download_link(text)
        except ValueError as error:
            self.rejected.emit(str(error))
            return None
        if key in self.pending_keys:
            self.rejected.emit("这条链接已在任务中，不会重复创建下载。")
            return None
        if not force:
            existing = self.store.find_source(key)
            if existing:
                self.duplicate.emit(existing)
                return None
        task = DownloadTask(url, platform, key, self.output)
        self.pending_keys.add(key)
        self.queue.append(task)
        self.queue_changed.emit()
        QTimer.singleShot(0, self._next)
        return task

    def _next(self):
        if self.active or self.closing or not self.queue:
            if not self.busy():
                self.idle.emit()
            return
        task = self.active = self.queue.popleft()
        self.last = task
        task.state, task.message = "running", "正在连接 " + task.platform.label
        process = self.process = QProcess(self)
        process._buffer, process._stderr = b"", b""
        process.setWorkingDirectory(str(APP_DIR))
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("VIDEO_DOWNLOADER_OUTPUT", str(task.output))
        environment.insert("PYTHONIOENCODING", "utf-8")
        process.setProcessEnvironment(environment)
        process.readyReadStandardOutput.connect(lambda: self._read(process, task))
        process.readyReadStandardError.connect(lambda: self._errors(process))
        process.finished.connect(lambda code, status: self._finished(process, task, code))
        process.errorOccurred.connect(lambda error: self._process_error(process, task, error))
        extra, snapshot = self.accounts.arguments(task.platform)
        if snapshot:
            def send():
                process.write(json.dumps(snapshot, ensure_ascii=False).encode("utf-8"))
                process.closeWriteChannel()
            process.started.connect(send)
        executable, args = self.command_factory([task.url, *extra])
        process.start(executable, args)
        self.changed.emit(task)
        self.queue_changed.emit()

    def _read(self, process, task):
        process._buffer += bytes(process.readAllStandardOutput())
        while b"\n" in process._buffer:
            line, process._buffer = process._buffer.split(b"\n", 1)
            self._consume(line, task)

    def _errors(self, process):
        data = bytes(process.readAllStandardError())
        process._stderr = (process._stderr + data)[-16000:]
        if data:
            self.log.emit(data.decode("utf-8", errors="replace"))

    def _consume(self, line, task):
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            self.log.emit(line.decode("utf-8", errors="replace"))
            return
        kind = event.get("event")
        if kind == "accounts":
            self.accounts.accept_sources(event["sources"], event.get("platform"))
        elif kind in {"stage", "login_source"}:
            task.message = event["message"]
            if kind == "stage":
                task.total = task.downloaded = 0
                task.speed = 0
        elif kind == "metadata":
            task.title = event.get("title") or task.title
        elif kind == "progress":
            task.downloaded = int(event.get("downloaded") or 0)
            task.total = int(event.get("total") or 0)
            task.speed = float(event.get("speed") or 0)
            task.eta = event.get("eta")
            task.message = "正在下载视频 / 音频"
        elif kind == "complete":
            task.result = event
            task.title = event.get("title") or task.title
            task.message = "完整性检查通过，正在保存到视频库…"
        elif kind == "error":
            task.error = task.message = str(event["message"])
        elif kind == "log":
            self.log.emit(str(event.get("message", "")))
        task.updated = time.monotonic()
        self.changed.emit(task)

    def _process_error(self, process, task, error):
        if error == QProcess.FailedToStart and self.process is process:
            task.error = "下载服务未能启动，请重新安装视频下载器。"
            self._finished(process, task, -1)

    def _finished(self, process, task, code):
        if self.process is not process:
            return
        self._read(process, task)
        self._errors(process)
        if process._buffer.strip():
            self._consume(process._buffer, task)
        self.process, self.active = None, None
        process.deleteLater()
        if task.cancelled:
            task.state, task.message = "cancelled", "已取消下载，可重试续传。"
        elif code == 0 and task.result and Path(task.result["path"]).exists():
            task.state = "saving"
            result = {**task.result, "source_key": task.key}
            self.catalogue_jobs.submit(lambda: self.store.upsert(result["path"], result, source_key=task.key, completed=True),
                                       lambda identifier: self._saved(task, identifier), lambda error: self._save_error(task, error))
        else:
            task.state = "failed"
            task.message = task.error or "下载未完成，请重试；需要登录时可在右上角设置中处理。"
        if task.state != "saving":
            self.pending_keys.discard(task.key)
        self.changed.emit(task)
        self.queue_changed.emit()
        QTimer.singleShot(0, self._next)

    def _saved(self, task, identifier):
        self.pending_keys.discard(task.key)
        task.state, task.message = "done", "下载完成，可前往我的视频查看。"
        task.result["library_id"] = identifier
        self.changed.emit(task)
        self.completed.emit(task.result)

    def _save_error(self, task, error):
        self.pending_keys.discard(task.key)
        task.state, task.message = "done", "视频已完整保存，但入库失败；请打开保存文件夹或刷新视频库。"
        self.log.emit("视频库：" + error)
        self.changed.emit(task)
        self.completed.emit(task.result)

    def cancel_current(self):
        task, process = self.active, self.process
        if not task or not process:
            return
        task.cancelled = True
        task.message = "正在取消下载…"
        self.changed.emit(task)
        pid = int(process.processId())
        if os.name == "nt" and pid:
            try:
                subprocess.Popen(["taskkill", "/PID", str(pid), "/T", "/F"],
                                 creationflags=subprocess.CREATE_NO_WINDOW,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                process.kill()
        else:
            process.kill()
        QTimer.singleShot(2000, lambda: process.state() != QProcess.NotRunning and process.kill() if self.process is process else None)

    def clear_queue(self):
        for task in self.queue:
            self.pending_keys.discard(task.key)
        self.queue.clear()
        self.queue_changed.emit()

    def shutdown(self):
        self.closing = True
        self.clear_queue()
        self.cancel_current()
