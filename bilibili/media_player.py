"""Local Qt Multimedia playback and an in-app viewer for existing albums."""
import json
import os
from pathlib import Path
import ctypes
import PySide6

# The bundled FFmpeg backend plays AV1/HEVC without requiring Windows codec packs.
# Explicit user overrides remain available for platform troubleshooting.
os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
_decoder_handles = []
if os.name == "nt":
    # Qt loads its media plugin from plugins/multimedia. Its codec DLLs live
    # beside PySide6 rather than beside that plugin; preload exact bundled files
    # so playback does not silently fall back to missing Windows codec packs.
    _qt_directory = Path(PySide6.__file__).parent
    try:
        _decoder_handles.append(os.add_dll_directory(str(_qt_directory)))
        for _pattern in ("avutil-*.dll", "swresample-*.dll", "swscale-*.dll", "avcodec-*.dll", "avformat-*.dll"):
            for _library in _qt_directory.glob(_pattern):
                _decoder_handles.append(ctypes.WinDLL(str(_library)))
    except OSError:
        pass  # The player reports the actual backend error and offers external playback.

from PySide6.QtCore import Qt, QUrl, Signal, QSize
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QPainter, QPixmap, QShortcut, QTransform
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QSlider, QToolButton, QVBoxLayout, QWidget

from media_library import gallery_assets
from ui_theme import COLORS, METRICS, SPACE, icon
from ui_widgets import ElidedLabel, clock_text, text_label


AUDIO_EXTENSIONS = frozenset({".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav", ".wma"})


class VideoSurface(QWidget):
    """Qt's local decoder feeds a native widget, including software/remote GPUs."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sink = QVideoSink(self)
        self.image = None
        self.sink.videoFrameChanged.connect(self.frame)

    def videoSink(self):
        return self.sink

    def frame(self, frame):
        if not frame.isValid():
            return
        image = frame.toImage()
        if image.isNull():
            return
        angle = frame.rotationAngle().value
        if angle:
            image = image.transformed(QTransform().rotate(angle))
        if frame.mirrored():
            image = image.mirrored(True, False)
        self.image = image
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(COLORS["video"]))
        if self.image is not None:
            size = self.image.size().scaled(self.size(), Qt.KeepAspectRatio)
            target = self.rect()
            target.setSize(size)
            target.moveCenter(self.rect().center())
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawImage(target, self.image)


class MediaWindow(QDialog):
    """Independent native windows; lifecycle links do not create a Win32 owner."""
    def __init__(self, source=None):
        super().__init__(None, Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint
                         | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.setWindowModality(Qt.NonModal)
        if source is not None:
            self.setStyleSheet(source.styleSheet())
            self.setWindowIcon(source.windowIcon())
            source.destroyed.connect(self.close)


class PlayerDialog(MediaWindow):
    delete_requested = Signal()
    export_audio_requested = Signal()

    def __init__(self, path, title="", parent=None):
        media_path = Path(path)
        if media_path.suffix.casefold() in AUDIO_EXTENSIONS:
            raise ValueError("音频请使用默认播放器打开。")
        super().__init__(parent)
        self.path = media_path
        self.setWindowTitle(title or self.path.stem)
        self.resize(960, 630)
        self.setMinimumSize(640, 420)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._was_maximized = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        layout.setSpacing(SPACE["md"])
        heading = QHBoxLayout()
        heading.addWidget(ElidedLabel(title or self.path.stem, role="taskTitle"), 1)
        heading.addWidget(text_label("本地播放", role="caption"))
        self.export_audio_button = QPushButton("导出 MP3")
        self.export_audio_button.clicked.connect(self.request_export_audio)
        self.export_audio_button.setEnabled(self.path.is_file())
        heading.addWidget(self.export_audio_button)
        self.delete_button = QToolButton()
        self.delete_button.setObjectName("sidebarAction")
        self.delete_button.setIcon(icon("trash", COLORS["text"]))
        self.delete_button.setAccessibleName("删除此视频")
        self.delete_button.setToolTip("删除此视频")
        self.delete_button.clicked.connect(self.delete_requested)
        heading.addWidget(self.delete_button)
        layout.addLayout(heading)
        self.video = VideoSurface()
        self.video.setMinimumHeight(210)
        layout.addWidget(self.video, 1)
        self.error_label = text_label("", role="error", wrap=True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.setAccessibleName("视频播放进度")
        layout.addWidget(self.seek)
        controls = QHBoxLayout()
        self.play_button = QPushButton("暂停")
        self.play_button.setIcon(icon("pause", COLORS["text"]))
        self.play_button.clicked.connect(self.toggle_play)
        controls.addWidget(self.play_button)
        self.time_label = text_label("00:00 / 00:00")
        self.time_label.setObjectName("muted")
        controls.addWidget(self.time_label)
        controls.addStretch()
        controls.addWidget(text_label("音量"))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(65)
        self.volume.setFixedWidth(110)
        self.volume.setAccessibleName("播放音量")
        controls.addWidget(self.volume)
        self.fullscreen_button = QPushButton("全屏")
        self.fullscreen_button.setIcon(icon("fullscreen", COLORS["text"]))
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        controls.addWidget(self.fullscreen_button)
        layout.addLayout(controls)
        fallback = QHBoxLayout()
        fallback.addWidget(text_label("本地播放 · 空格暂停 · F11 全屏", role="muted"))
        fallback.addStretch()
        self.external = QPushButton("使用默认播放器打开")
        self.external.setObjectName("link")
        self.external.clicked.connect(self.open_external)
        fallback.addWidget(self.external)
        layout.addLayout(fallback)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.65)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video.sink)
        self.player.positionChanged.connect(self._position)
        self.player.durationChanged.connect(self._duration)
        self.player.playbackStateChanged.connect(self._state)
        self.player.errorOccurred.connect(self._error)
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.seek.sliderReleased.connect(lambda: self.player.setPosition(self.seek.value()))
        self.volume.valueChanged.connect(lambda value: self.audio.setVolume(value / 100))
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self.toggle_play)
        QShortcut(QKeySequence(Qt.Key_F11), self, activated=self.toggle_fullscreen)
        if self.path.is_file():
            self.player.setSource(QUrl.fromLocalFile(str(self.path.resolve())))
            self.player.play()
        else:
            self._error(None, "文件已被移动或删除，请返回视频库刷新。")
            self.external.setEnabled(False)

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def request_export_audio(self):
        if self.path.is_file():
            self.export_audio_requested.emit()

    def _position(self, position):
        if not self.seek.isSliderDown():
            self.seek.setValue(position)
        self.time_label.setText(clock_text(position / 1000) + " / " + clock_text(self.player.duration() / 1000))

    def _duration(self, duration):
        self.seek.setRange(0, max(0, duration))
        self._position(self.player.position())

    def _state(self, state):
        self.play_button.setText("暂停" if state == QMediaPlayer.PlayingState else "播放")
        self.play_button.setIcon(icon("pause" if state == QMediaPlayer.PlayingState else "play", COLORS["text"]))

    def _error(self, error, message=""):
        self.error_label.setText("软件内播放失败：" + (message or self.player.errorString() or "当前解码组件无法播放此文件。")
                                 + " 可尝试下方的默认播放器。")
        self.error_label.show()
        self.play_button.setEnabled(False)

    def open_external(self):
        if self.path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path.resolve())))

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized() if self._was_maximized else self.showNormal()
            self.fullscreen_button.setText("全屏")
        else:
            self._was_maximized = self.isMaximized()
            self.showFullScreen()
            self.fullscreen_button.setText("退出全屏")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
            event.accept()
        else:
            super().keyPressEvent(event)

    def done(self, result):
        self.player.stop()
        self.player.setSource(QUrl())
        super().done(result)

    def closeEvent(self, event):
        self.player.stop()
        self.player.setSource(QUrl())
        super().closeEvent(event)


class GalleryDialog(MediaWindow):
    delete_requested = Signal()
    asset_delete_requested = Signal(object, object)

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.setWindowTitle(item["title"])
        self.resize(900, 650)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.item = item
        self.media = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["xl"], SPACE["xl"], SPACE["xl"])
        layout.setSpacing(SPACE["lg"])
        self.assets = gallery_assets(item["path"], json.loads(item["metadata"]))
        heading = QHBoxLayout()
        heading.addWidget(ElidedLabel(item["title"], role="taskTitle"), 1)
        self.summary = text_label("", role="caption")
        heading.addWidget(self.summary)
        self.delete_button = QToolButton()
        self.delete_button.setObjectName("sidebarAction")
        self.delete_button.setIcon(icon("trash", COLORS["text"]))
        self.delete_button.setToolTip("删除整个图文作品")
        self.delete_button.setAccessibleName("删除整个图文作品")
        self.delete_button.clicked.connect(self.delete_requested)
        heading.addWidget(self.delete_button)
        layout.addLayout(heading)
        self.preview = QLabel()
        self.preview.setObjectName("galleryPreview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(320, 260)
        layout.addWidget(self.preview, 1)
        self.list = QListWidget()
        self.list.setObjectName("assetList")
        self.list.setAccessibleName("作品内的图片、实况视频和配乐")
        self.list.setMaximumHeight(140)
        self.list.currentRowChanged.connect(self.select)
        layout.addWidget(self.list)
        actions = QHBoxLayout()
        self.delete_asset_button = QPushButton(icon("trash", COLORS["text"]), "删除图片")
        self.delete_asset_button.clicked.connect(self.request_asset_delete)
        actions.addWidget(self.delete_asset_button)
        actions.addStretch()
        self.open_button = QPushButton("在软件内播放选中媒体")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self.play_selected)
        actions.addWidget(self.open_button)
        layout.addLayout(actions)
        self.update_item(item)
        QShortcut(QKeySequence(Qt.Key_Delete), self, activated=self.request_asset_delete)

    def update_item(self, item):
        self.item = item
        previous = max(0, self.list.currentRow())
        self.assets = gallery_assets(item["path"], json.loads(item["metadata"]))
        counts = {kind: sum(asset["kind"] == kind for asset in self.assets) for kind in ("image", "live_photo", "music")}
        self.summary.setText(" · ".join(f"{counts[kind]} {unit}" for kind, unit in
                                      (("image", "张图片"), ("live_photo", "段实况"), ("music", "首配乐")) if counts[kind]))
        kinds = {"image": "图片", "live_photo": "实况视频", "music": "配乐"}
        counters = {}
        self.list.clear()
        for asset in self.assets:
            kind = asset["kind"]
            counters[kind] = counters.get(kind, 0) + 1
            row = QListWidgetItem(f"{kinds.get(kind, '文件')} {counters[kind]:02d}")
            row.setToolTip(Path(asset["path"]).name)
            self.list.addItem(row)
        self.list.setCurrentRow(min(previous, len(self.assets) - 1))

    def request_asset_delete(self):
        index = self.list.currentRow()
        if 0 <= index < len(self.assets):
            self.asset_delete_requested.emit(self.item, self.assets[index])

    def release_selected_media(self):
        if self.media:
            try:
                self.media.close()
            except RuntimeError:
                pass
            self.media = None
        self.preview.clear()

    def select(self, index):
        if not 0 <= index < len(self.assets):
            return
        asset = self.assets[index]
        kind = {"image": "图片", "live_photo": "实况视频", "music": "配乐"}.get(asset["kind"], "文件")
        self.delete_asset_button.setText("删除" + kind)
        path = Path(asset["path"])
        if asset["kind"] == "image" and path.is_file():
            self.preview.setPixmap(QPixmap(str(path)).scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.open_button.hide()
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("点击下方按钮播放实况视频或配乐。" if path.is_file() else "文件已被移动或删除。")
            self.open_button.setText("使用默认播放器播放" if asset["kind"] == "music" or path.suffix.casefold() in AUDIO_EXTENSIONS
                                     else "在软件内播放选中媒体")
            self.open_button.setEnabled(path.is_file())
            self.open_button.show()

    def play_selected(self):
        index = self.list.currentRow()
        if 0 <= index < len(self.assets):
            asset = dict(self.assets[index])
            path = Path(asset["path"])
            if asset["kind"] == "music" or path.suffix.casefold() in AUDIO_EXTENSIONS:
                if path.is_file():
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
                return
            self.release_selected_media()
            self.media = PlayerDialog(asset["path"], self.windowTitle(), self)
            self.media.delete_requested.connect(lambda: self.asset_delete_requested.emit(self.item, asset))
            self.media.show()

    def done(self, result):
        self.release_selected_media()
        super().done(result)

    def closeEvent(self, event):
        self.release_selected_media()
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "list"):
            self.select(self.list.currentRow())
