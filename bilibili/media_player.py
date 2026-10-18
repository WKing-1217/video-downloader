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

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QPainter, QPixmap, QShortcut, QTransform
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QPushButton, QSlider, QVBoxLayout, QWidget

from media_library import gallery_assets
from ui_widgets import clock_text, text_label


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
        painter.fillRect(self.rect(), QColor("#11151e"))
        if self.image is not None:
            size = self.image.size().scaled(self.size(), Qt.KeepAspectRatio)
            target = self.rect()
            target.setSize(size)
            target.moveCenter(self.rect().center())
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawImage(target, self.image)


class PlayerDialog(QDialog):
    def __init__(self, path, title="", parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.setWindowTitle(title or self.path.stem)
        self.resize(960, 630)
        self.setMinimumSize(640, 420)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._was_maximized = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        self.video = VideoSurface()
        self.video.setMinimumHeight(210)
        self.video.setStyleSheet("background: #11151e;")
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
        self.play_button.clicked.connect(self.toggle_play)
        controls.addWidget(self.play_button)
        self.time_label = text_label("00:00 / 00:00")
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
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        controls.addWidget(self.fullscreen_button)
        layout.addLayout(controls)
        fallback = QHBoxLayout()
        fallback.addWidget(text_label("本地播放 · 空格暂停 · F11 全屏", role="muted"))
        fallback.addStretch()
        self.external = QPushButton("使用默认播放器打开")
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

    def _position(self, position):
        if not self.seek.isSliderDown():
            self.seek.setValue(position)
        self.time_label.setText(clock_text(position / 1000) + " / " + clock_text(self.player.duration() / 1000))

    def _duration(self, duration):
        self.seek.setRange(0, max(0, duration))
        self._position(self.player.position())

    def _state(self, state):
        self.play_button.setText("暂停" if state == QMediaPlayer.PlayingState else "播放")

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


class GalleryDialog(QDialog):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.setWindowTitle(item["title"])
        self.resize(900, 650)
        self.setAttribute(Qt.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(320, 260)
        layout.addWidget(self.preview, 1)
        self.assets = gallery_assets(item["path"], json.loads(item["metadata"]))
        self.list = QListWidget()
        self.list.setMaximumHeight(140)
        kinds = {"image": "图片", "live_photo": "实况视频", "music": "配乐"}
        for asset in self.assets:
            self.list.addItem(kinds.get(asset["kind"], "文件") + " · " + Path(asset["path"]).name)
        self.list.currentRowChanged.connect(self.select)
        layout.addWidget(self.list)
        self.open_button = QPushButton("在软件内播放选中媒体")
        self.open_button.clicked.connect(self.play_selected)
        layout.addWidget(self.open_button)
        self.list.setCurrentRow(0)

    def select(self, index):
        if not 0 <= index < len(self.assets):
            return
        asset = self.assets[index]
        path = Path(asset["path"])
        if asset["kind"] == "image" and path.is_file():
            self.preview.setPixmap(QPixmap(str(path)).scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.open_button.hide()
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("点击下方按钮播放实况视频或配乐。" if path.is_file() else "文件已被移动或删除。")
            self.open_button.setEnabled(path.is_file())
            self.open_button.show()

    def play_selected(self):
        index = self.list.currentRow()
        if 0 <= index < len(self.assets):
            self.media = PlayerDialog(self.assets[index]["path"], self.windowTitle(), self)
            self.media.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "list"):
            self.select(self.list.currentRow())
