"""Qt orchestration for verified media moves, including interrupted moves."""
import json
from pathlib import Path
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import QDialog, QHBoxLayout, QProgressBar, QPushButton, QVBoxLayout

from media_storage import MediaMigration
from runtime_paths import output_dir
from ui_theme import DIALOG, SPACE
from ui_widgets import ElidedLabel, size_text, text_label


class MigrationDialog(QDialog):
    def __init__(self, controller):
        super().__init__(controller.window)
        self.controller = controller
        self.setWindowTitle("迁移下载位置")
        self.resize(600, 250)
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*([DIALOG["inset"]] * 4))
        layout.setSpacing(SPACE["lg"])
        layout.addWidget(text_label("迁移下载位置", role="sectionTitle"))
        self.target = ElidedLabel("")
        layout.addWidget(self.target)
        self.status = text_label("", role="muted", wrap=True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)
        actions = QHBoxLayout()
        actions.addStretch()
        self.retry = QPushButton("继续处理")
        self.retry.clicked.connect(controller.recover)
        self.retry.hide()
        actions.addWidget(self.retry)
        self.finish_button = QPushButton("取消迁移")
        self.finish_button.clicked.connect(self.finish_or_cancel)
        actions.addWidget(self.finish_button)
        layout.addLayout(actions)

    def finish_or_cancel(self):
        if self.controller.running:
            if self.controller.service.phase in {"idle", "copying"}:
                self.controller.service.cancelled.set()
                self.finish_button.setEnabled(False)
                self.status.setText("正在取消，原视频保留…")
        else:
            self.accept()

    def reject(self):
        if self.controller.running:
            self.finish_or_cancel()
        else:
            super().reject()

    def closeEvent(self, event):
        if self.controller.running:
            self.finish_or_cancel()
            event.ignore()
        else:
            super().closeEvent(event)


class StorageController(QObject):
    changed = Signal()
    location_changed = Signal(str, object)
    progress_received = Signal(object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.service = MediaMigration(window.store)
        self.running = False
        self.dialog = None
        self.message = ""
        self.progress_received.connect(self.render_progress, Qt.QueuedConnection)

    def pending_phase(self):
        try:
            return json.loads(self.service.journal.read_text(encoding="utf-8")).get("phase", "")
        except (OSError, ValueError):
            return "invalid" if self.service.pending() else ""

    def start(self, folder=None):
        window = self.window
        if self.running:
            if self.dialog:
                self.dialog.show()
                self.dialog.raise_()
            return False
        if window.closing or window.updater.installing:
            return False
        if window.library.storage_busy:
            self.message = "正在处理作品，请稍后再更改位置。"
            self.changed.emit()
            return False
        if window.downloads.busy():
            self.message = "请等待下载完成，或取消下载后再更改位置。"
            window.library.notice.setText(self.message)
            self.changed.emit()
            return False
        recovering = self.service.pending()
        if not recovering and not folder:
            return False
        if self.dialog:
            self.dialog.close()
        self.running = True
        self.service.cancelled.clear()
        self.service.phase = "idle"
        self.message = "正在等待视频库完成同步…"
        window.downloads.output_locked = True
        window.library.set_storage_busy(True)
        window.release_media()
        self.dialog = MigrationDialog(self)
        self.dialog.target.setText(str(folder or output_dir()))
        self.dialog.status.setText(self.message)
        self.dialog.show()
        self.changed.emit()

        def wait_for_library():
            if window.library.pool.active:
                QTimer.singleShot(50, wait_for_library)
                return
            if window.closing or self.service.cancelled.is_set():
                self.finished({"cancelled": True, "cleanup_pending": recovering})
                return
            last = [0, ""]
            def progress(phase, done, total):
                now = time.monotonic()
                if now - last[0] >= .05 or last[1] != phase or done == total:
                    last[:] = [now, phase]
                    self.progress_received.emit((phase, done, total))
            window.background.submit(lambda: self.service.recover(progress) if recovering
                                     else self.service.run(folder, progress), self.finished, self.failed)
        QTimer.singleShot(0, wait_for_library)
        return True

    def recover(self):
        return self.start()

    @Slot(object)
    def render_progress(self, value):
        phase, done, total = value
        if not self.dialog or not self.running:
            return
        if total:
            self.dialog.progress.setRange(0, 1000)
            self.dialog.progress.setValue(round(done / total * 1000))
        else:
            self.dialog.progress.setRange(0, 0)
        labels = {"copying": "正在复制并校验", "switching": "正在更新视频库", "cleaning": "正在清理旧文件"}
        self.message = labels.get(phase, phase)
        if phase == "copying":
            self.message += f" · {size_text(done)} / {size_text(total)}"
        self.dialog.status.setText(self.message)
        self.dialog.finish_button.setEnabled(phase == "copying" and not self.service.cancelled.is_set())

    def _resume(self):
        self.running = False
        self.window.downloads.output_locked = self.pending_phase() not in {"", "cleaning"}
        self.window.library.set_storage_busy(False)
        self.window.library.reload()
        self.window.library.refresh()

    def finished(self, result):
        if not result.get("cancelled"):
            self.location_changed.emit(result["target"], result)
            self.message = "位置已更改，原下载文件已迁移。"
            if result.get("cleanup_pending"):
                self.message = "视频已迁移，部分旧文件被占用，解除占用后可继续清理。"
            elif result.get("changed_originals"):
                self.message = "视频已迁移，迁移期间被修改的原文件已保留。"
            elif result.get("retained_directories"):
                self.message = "视频已迁移，旧目录中的其他文件已保留。"
        else:
            self.message = "迁移已取消，原视频和保存位置保留。"
        self._resume()
        self._show_result()

    def failed(self, error):
        # A durable switch may need to be resumed after a filesystem failure.
        # In cleanup phase the new catalogue is already committed and usable.
        if self.pending_phase() == "cleaning":
            self.location_changed.emit(str(output_dir()), {})
        self.message = "迁移未完成：" + error
        self.window.add_log(self.message)
        self._resume()
        self._show_result()

    def _show_result(self):
        self.window.library.notice.setText(self.message)
        if self.dialog:
            self.dialog.status.setText(self.message)
            self.dialog.progress.setRange(0, 1000)
            self.dialog.progress.setValue(1000 if not self.service.pending() else 0)
            self.dialog.finish_button.setText("完成")
            self.dialog.finish_button.setEnabled(True)
            self.dialog.retry.setVisible(self.service.pending())
        self.changed.emit()
