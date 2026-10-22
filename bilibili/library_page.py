"""Virtualized thumbnail cards, background scanning, safe catalogue actions."""
from collections import OrderedDict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading

from PySide6.QtCore import QAbstractListModel, QEvent, QFileSystemWatcher, QModelIndex, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath, QPixmap, QPen
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QListView, QMenu,
                              QMessageBox, QPushButton, QStackedWidget, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)
from async_jobs import BackgroundPool
from media_library import gallery_assets
from runtime_paths import data_dir, tool
from ui_theme import COLORS, METRICS, SPACE, icon
from ui_widgets import EmptyState, LocationBar, clock_text, size_text, text_label


def thumbnail_and_metadata(item, cache):
    path = Path(item["path"])
    if not path.exists():
        return item["id"], {"state": "missing"}
    metadata = json.loads(item["metadata"])
    source = path
    result = {}
    if item["kind"] == "gallery":
        assets = gallery_assets(path, metadata)
        source = next((Path(asset["path"]) for asset in assets if asset["kind"] == "image" and Path(asset["path"]).is_file()), path)
    elif item["state"] == "pending":
        probe = subprocess.run([tool("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                               capture_output=True, encoding="utf-8", errors="replace", timeout=12,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            data = json.loads(probe.stdout)
            duration = float(data.get("format", {}).get("duration") or 0)
            valid = any(stream.get("codec_type") == "video" for stream in data.get("streams", []))
            if probe.returncode or not valid or duration <= 0:
                return item["id"], {"state": "unreadable"}
            result.update(duration=duration, size=path.stat().st_size, state="ready")
        except (ValueError, TypeError):
            return item["id"], {"state": "unreadable"}
    signature = f"{path}|{item['mtime']}|{item['size']}"
    final = Path(cache) / (hashlib.sha256(signature.encode()).hexdigest() + ".jpg")
    if final.is_file():
        return item["id"], {**result, "thumb": str(final)}
    temporary = final.with_suffix(".tmp.jpg")
    command = [tool("ffmpeg"), "-v", "error", "-nostdin", "-y"]
    if item["kind"] != "gallery":
        command += ["-ss", str(min(4, (result.get("duration") or item["duration"] or 0) / 10))]
    command += ["-i", str(source), "-frames:v", "1", "-vf",
                "scale=480:270:force_original_aspect_ratio=decrease,pad=480:270:(ow-iw)/2:(oh-ih)/2:color=0x18202d",
                "-q:v", "3", "-threads", "1", str(temporary)]
    try:
        run = subprocess.run(command, capture_output=True, timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if run.returncode == 0 and temporary.is_file() and temporary.stat().st_size:
            temporary.replace(final)
            result["thumb"] = str(final)
    finally:
        temporary.unlink(missing_ok=True)
    return item["id"], result


class MediaModel(QAbstractListModel):
    Row = Qt.UserRole + 1
    record_changed = Signal(int, object)

    def __init__(self, store, pool, parent=None):
        super().__init__(parent)
        self.store, self.pool = store, pool
        self.rows = []
        self.all_rows = []
        self.query = ""
        self.oldest = False
        self.requested = set()
        self.pixmaps = OrderedDict()
        self.cache = data_dir() / "thumbnails"
        self.cache.mkdir(exist_ok=True)
        self.closing = False

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        item = self.rows[index.row()]
        if role == Qt.DisplayRole:
            return item["title"]
        if role == self.Row:
            return item
        if role == Qt.ToolTipRole:
            return item["title"] + "\n" + item["path"]

    def set_rows(self, rows):
        self.all_rows = rows
        self.filter(self.query, self.oldest)

    def filter(self, query, oldest=False):
        self.query, self.oldest = query.strip().casefold(), oldest
        rows = [item for item in self.all_rows if self.query in item["title"].casefold()]
        rows.sort(key=lambda item: (item["completed"], item["id"]), reverse=not oldest)
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def thumbnail(self, item):
        thumb = item.get("thumb")
        if thumb and Path(thumb).is_file():
            if thumb not in self.pixmaps:
                self.pixmaps[thumb] = QPixmap(thumb)
                while len(self.pixmaps) > 100:
                    self.pixmaps.popitem(last=False)
            else:
                self.pixmaps.move_to_end(thumb)
            return self.pixmaps[thumb]
        key = (item["id"], item["mtime"], item["size"])
        if key not in self.requested and item["state"] != "missing" and not self.closing:
            # The delegate calls this for visible rows, not for every file.
            self.requested.add(key)
            def work(record=dict(item)):
                result = thumbnail_and_metadata(record, self.cache)
                if result[1]:
                    self.store.update(result[0], **result[1])
                return result
            self.pool.submit(work, self._thumbnail_ready)
        return None

    def _thumbnail_ready(self, result):
        identifier, values = result
        if not values or self.closing:
            return
        for item in self.all_rows:
            if item["id"] == identifier:
                item.update(values)
        for row, item in enumerate(self.rows):
            if item["id"] == identifier:
                self.dataChanged.emit(self.index(row), self.index(row))
        self.record_changed.emit(identifier, values)


class MediaDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        view = self.parent()
        size = view.gridSize() if isinstance(view, QListView) else QSize()
        return size if size.isValid() else QSize(METRICS["card_width"], METRICS["card_height"])

    def paint(self, painter, option, index):
        item = index.data(MediaModel.Row)
        if not item:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        inset_size = METRICS["card_inset"]
        card = option.rect.adjusted(inset_size, inset_size, -inset_size, -SPACE["sm"])
        selected = bool(option.state & (QStyle.State_Selected | QStyle.State_HasFocus))
        hovered = bool(option.state & QStyle.State_MouseOver)
        painter.setPen(QPen(QColor(COLORS["accent"] if selected else COLORS["border"]), 2 if selected else 1))
        painter.setBrush(QColor(COLORS["surface"]))
        radius = METRICS["radius"]
        painter.drawRoundedRect(card, radius, radius)
        picture = QRect(card.left(), card.top(), card.width(), round(card.width() * 9 / 16))
        clip = QPainterPath()
        clip.addRoundedRect(card.adjusted(1, 1, -1, -1), radius, radius)
        painter.setClipPath(clip)
        pixmap = index.model().thumbnail(item)
        if pixmap and not pixmap.isNull():
            painter.drawPixmap(picture, pixmap)
        else:
            painter.fillRect(picture, QColor(COLORS["thumb"]))
            placeholder = QRect(0, 0, METRICS["badge_icon"], METRICS["badge_icon"])
            placeholder.moveCenter(picture.center())
            icon("play" if item["kind"] == "video" else "nav-library", COLORS["muted"]).paint(painter, placeholder)
        font = QFont("Segoe UI")
        font.setPixelSize(METRICS["caption"])
        font.setWeight(QFont.Medium)
        painter.setFont(font)
        duration = clock_text(item["duration"]) if item["duration"] else "图文" if item["kind"] == "gallery" else "视频"
        badge_width = painter.fontMetrics().horizontalAdvance(duration) + SPACE["lg"]
        badge = QRect(picture.right() - badge_width - SPACE["sm"], picture.bottom() - 30, badge_width, SPACE["xxl"])
        overlay = QColor(COLORS["overlay"])
        overlay.setAlpha(210)
        painter.setPen(Qt.NoPen)
        painter.setBrush(overlay)
        painter.drawRoundedRect(badge, SPACE["xs"], SPACE["xs"])
        painter.setPen(QColor(COLORS["white"]))
        painter.drawText(badge, Qt.AlignCenter, duration)
        if hovered or selected:
            play = QRect(0, 0, 36, 36)
            play.moveCenter(picture.center())
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(COLORS["surface"]))
            painter.drawEllipse(play)
            icon("play", COLORS["accent"]).paint(painter, play.adjusted(8, 8, -8, -8))
        painter.setClipping(False)
        inset = card.adjusted(SPACE["md"], picture.height() + SPACE["sm"], -SPACE["md"], -SPACE["sm"])
        painter.setPen(QColor(COLORS["text"]))
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(METRICS["body"])
        font.setWeight(QFont.Medium)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text = metrics.elidedText(item["title"], Qt.ElideRight, inset.width())
        painter.drawText(QRect(inset.left(), inset.top(), inset.width(), SPACE["xxl"]), Qt.AlignVCenter, text)
        font.setPixelSize(METRICS["caption"])
        font.setWeight(QFont.Normal)
        painter.setFont(font)
        painter.setPen(QColor(COLORS["muted"]))
        platform = json.loads(item["metadata"]).get("platform", "")
        description = {"bilibili": "Bilibili", "douyin": "抖音", "x": "X"}.get(platform, "图文作品" if item["kind"] == "gallery" else "本地视频")
        if item["state"] == "missing":
            description = "文件已移动或删除"
            painter.setPen(QColor(COLORS["danger"]))
        elif item["state"] == "unreadable":
            description = "无法读取，点击查看原因"
            painter.setPen(QColor(COLORS["danger"]))
        painter.drawText(QRect(inset.left(), inset.top() + 28, inset.width(), SPACE["xl"]), Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(description + " · " + size_text(item["size"]), Qt.ElideRight, inset.width()))
        painter.setPen(QColor(COLORS["muted"]))
        painter.drawText(QRect(inset.left(), inset.top() + 50, inset.width(), SPACE["xl"]), Qt.AlignVCenter,
                         datetime.fromtimestamp(item["completed"]).strftime("%Y.%m.%d  %H:%M"))
        painter.restore()


class MediaGrid(QListView):
    open_requested = Signal(object)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.position().toPoint())
            if index.isValid():
                self.open_requested.emit(index.data(MediaModel.Row))

    def keyPressEvent(self, event):
        if event.key() in {Qt.Key_Return, Qt.Key_Enter} and self.currentIndex().isValid():
            self.open_requested.emit(self.currentIndex().data(MediaModel.Row))
            event.accept()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_grid()

    def viewportEvent(self, event):
        if event.type() == QEvent.Resize:
            QTimer.singleShot(0, self.update_grid)
        return super().viewportEvent(event)

    def update_grid(self):
        width = max(220, self.viewport().width())
        columns = max(1, width // METRICS["card_width"])
        # Keep enough space for a scrollbar even while a hidden page's layout
        # still reports its previous viewport width.
        cell = (width - METRICS["gap"]) // columns
        size = QSize(cell, round((cell - METRICS["card_inset"] * 2) * 9 / 16) + METRICS["card_footer"])
        if self.gridSize() != size:
            self.setGridSize(size)


class LibraryPage(QWidget):
    open_requested = Signal(object)
    download_requested = Signal()
    output_changed = Signal(str)
    refreshed = Signal(object)
    log = Signal(str)

    def __init__(self, store, output, parent=None):
        super().__init__(parent)
        self.store, self.output = store, Path(output)
        self.pool = BackgroundPool(self, 2)
        self.scan_cancel = threading.Event()
        self.scanning = False
        self.closing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])
        toolbar = QHBoxLayout()
        toolbar.setSpacing(SPACE["md"])
        self.search = QLineEdit()
        self.search.setObjectName("searchInput")
        self.search.setPlaceholderText("搜索视频名称")
        self.search.setAccessibleName("搜索视频名称")
        self.search.addAction(icon("search", COLORS["muted"]), QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        toolbar.addWidget(self.search, 1)
        self.sort = QComboBox()
        self.sort.setAccessibleName("按下载时间排序")
        self.sort.addItems(["最近下载优先", "最早下载优先"])
        toolbar.addWidget(self.sort)
        self.refresh_button = QPushButton(icon("nav-update", COLORS["muted"]), "刷新")
        self.refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(self.refresh_button)
        layout.addLayout(toolbar)
        self.notice = text_label("正在导入原有视频…", role="muted", wrap=True)
        layout.addWidget(self.notice)
        self.model = MediaModel(store, self.pool, self)
        self.grid = MediaGrid()
        self.grid.setObjectName("libraryGrid")
        self.grid.setAccessibleName("作品列表，按回车打开，右键管理文件")
        self.grid.setMouseTracking(True)
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setWrapping(True)
        self.grid.setUniformItemSizes(True)
        self.grid.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.grid.setModel(self.model)
        self.grid.setItemDelegate(MediaDelegate(self.grid))
        self.grid.open_requested.connect(self.open_requested)
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self.context_menu)
        self.empty = EmptyState("暂无视频", "", action="下载")
        self.empty.activated.connect(self._empty_action)
        self.results = QStackedWidget()
        self.results.addWidget(self.grid)
        self.results.addWidget(self.empty)
        layout.addWidget(self.results, 1)
        self.search.textChanged.connect(self.filter)
        self.sort.currentIndexChanged.connect(self.filter)
        self.location_bar = LocationBar(self.output)
        self.location = self.location_bar.location
        self.folder_button = self.location_bar.folder_button
        self.choose_button = self.location_bar.choose_button
        self.location_bar.open_requested.connect(self.open_folder)
        self.location_bar.change_requested.connect(self.choose_output)
        layout.addWidget(self.location_bar)
        self.watcher = QFileSystemWatcher(self)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(1200)
        self.debounce.timeout.connect(self.refresh)
        self.watcher.directoryChanged.connect(lambda _: self.debounce.start())
        self.periodic = QTimer(self)
        self.periodic.setInterval(25000)
        self.periodic.timeout.connect(self.refresh)
        self.periodic.start()
        self.store.add_root(self.output)
        self.reload()

    def filter(self, *_):
        self.model.filter(self.search.text(), self.sort.currentIndex() == 1)
        self._notice()

    def _notice(self):
        missing = sum(item["state"] == "missing" for item in self.model.all_rows)
        text = f"共 {len(self.model.all_rows)} 个作品"
        if missing:
            text += f"，其中 {missing} 个文件已移动或删除"
        if self.search.text():
            text += f" · 找到 {len(self.model.rows)} 个"
        self.notice.setText(text)
        self.results.setCurrentWidget(self.grid if self.model.rows else self.empty)
        searching = bool(self.search.text())
        self.empty.title.setText("未找到视频" if searching else "暂无视频")
        self.empty.hint.setText("")
        self.empty.button.setText("清空搜索" if searching else "下载")

    def _empty_action(self):
        if self.search.text():
            self.search.clear()
        else:
            self.download_requested.emit()

    def reload(self):
        if not self.closing:
            self.model.set_rows(self.store.rows())
            self._notice()
            self.refreshed.emit(self.model.all_rows)

    def refresh(self):
        if self.scanning or self.closing:
            return
        self.scanning = True
        self.refresh_button.setEnabled(False)
        self.notice.setText("正在同步本地文件…")
        self.pool.submit(lambda: self.store.scan(self.scan_cancel), self._scanned, self._scan_error)

    def _scanned(self, count):
        self.scanning = False
        self.refresh_button.setEnabled(True)
        self.reload()
        roots = [path for path in self.store.roots() if Path(path).is_dir()]
        existing = set(self.watcher.directories())
        added = [path for path in roots if path not in existing][:128]
        if added:
            self.watcher.addPaths(added)

    def _scan_error(self, error):
        self.scanning = False
        self.refresh_button.setEnabled(True)
        self.notice.setText("同步未完成，可点击刷新重试。已有记录仍保留。")
        self.log.emit("视频库扫描：" + error)

    def open_folder(self):
        try:
            self.output.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output)))
        except OSError as error:
            self.notice.setText("无法打开目录：" + str(error))

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, "选择后续视频的保存位置", str(self.output))
        if folder:
            self.output_changed.emit(folder)

    def set_output(self, folder):
        self.store.add_root(self.output)
        self.output = Path(folder)
        self.store.add_root(self.output)
        self.location.setText(str(self.output))
        self.refresh()

    def context_menu(self, point):
        index = self.grid.indexAt(point)
        item = index.data(MediaModel.Row)
        if not item:
            return
        menu = QMenu(self)
        menu.addAction("播放 / 查看作品", lambda: self.open_requested.emit(item))
        menu.addAction("打开文件所在位置", lambda: self.reveal(item))
        menu.addAction("复制文件路径", lambda: self._copy_path(item))
        menu.addSeparator()
        menu.addAction("删除下载记录（保留文件）", lambda: self.remove_record(item))
        menu.addAction("删除本地文件…", lambda: self.delete_file(item))
        menu.exec(self.grid.viewport().mapToGlobal(point))

    def _copy_path(self, item):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(item["path"])

    def reveal(self, item):
        path = Path(item["path"])
        if os.name == "nt" and path.exists():
            # Explorer's /select argument is passed as one literal argv item.
            subprocess.Popen(["explorer.exe", "/select,", str(path)], creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def remove_record(self, item):
        self.store.remove_record(item["id"])
        self.reload()
        self.notice.setText("已移除下载记录，本地文件保留。")

    def delete_file(self, item):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("删除本地文件")
        dialog.setTextFormat(Qt.PlainText)
        dialog.setText("确定删除本地文件？此操作不会只移除记录。\n\n" + item["title"])
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        dialog.setDefaultButton(QMessageBox.Cancel)
        if dialog.exec() != QMessageBox.Yes:
            return
        try:
            self.store.delete_files(item["id"])
            self.reload()
        except OSError as error:
            self.notice.setText("文件未能删除，可能正被播放器占用：" + str(error))
            self.refresh()

    def shutdown(self):
        self.closing = self.model.closing = True
        self.scan_cancel.set()
        self.pool.discard_queued()
        self.periodic.stop()
        self.debounce.stop()
