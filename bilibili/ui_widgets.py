"""Shared native presentation controls; paste always requires user intent."""
from collections import OrderedDict

from PySide6.QtCore import Qt, Signal, QSize, QRect, QTimer
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QMenu, QPushButton, QSizePolicy, QStyle, QStyledItemDelegate, QVBoxLayout)
from ui_theme import COLORS, HOME, METRICS, SPACE, icon


def text_label(text="", *, role=None, wrap=False):
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(wrap)
    if wrap:
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    if role:
        label.setObjectName(role)
    return label


def panel(role="panel"):
    frame = QFrame()
    frame.setObjectName(role)
    layout = QVBoxLayout(frame)
    inset = SPACE["xxl"]
    layout.setContentsMargins(inset, inset, inset, inset)
    layout.setSpacing(SPACE["lg"])
    return frame, layout


def set_tone(widget, tone):
    if widget.property("tone") != tone:
        widget.setProperty("tone", tone)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


def divider():
    line = QFrame()
    line.setObjectName("divider")
    line.setFixedHeight(1)
    return line


class ElidedLabel(QLabel):
    """Keep long paths/titles accessible without dictating the window width."""
    def __init__(self, text="", *, role="muted", parent=None):
        super().__init__(text, parent)
        self.setTextFormat(Qt.PlainText)
        self.setObjectName(role)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setToolTip(text)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)

    def minimumSizeHint(self):
        return QSize(0, self.fontMetrics().height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().windowText().color())
        painter.setFont(self.font())
        painter.drawText(self.contentsRect(), Qt.AlignLeft | Qt.AlignVCenter,
                         self.fontMetrics().elidedText(self.text(), Qt.ElideRight, self.contentsRect().width()))


class IconBadge(QLabel):
    def __init__(self, name, *, tone="neutral", parent=None):
        super().__init__(parent)
        self.setObjectName("iconBadge")
        self.setFixedSize(METRICS["badge_icon"], METRICS["badge_icon"])
        self.setAlignment(Qt.AlignCenter)
        self.set_icon(name, tone)

    def set_icon(self, name, tone="neutral"):
        color = COLORS.get({"active": "accent", "success": "success", "danger": "danger"}.get(tone, "muted"))
        self.setPixmap(icon(name, color).pixmap(QSize(METRICS["nav_icon"], METRICS["nav_icon"]), self.devicePixelRatioF()))
        set_tone(self, tone)


class EmptyState(QFrame):
    activated = Signal()

    def __init__(self, title, hint, *, image="nav-library", action="", compact=False, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        inset = SPACE["lg"] if compact else SPACE["page"]
        layout.setContentsMargins(inset, inset, inset, inset)
        layout.setSpacing(SPACE["sm"])
        layout.addStretch()
        self.badge = IconBadge(image)
        layout.addWidget(self.badge, 0, Qt.AlignHCenter)
        layout.addSpacing(SPACE["xs"])
        self.title = text_label(title, role="taskTitle")
        self.title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title)
        self.hint = text_label(hint, role="muted", wrap=True)
        self.hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.hint)
        self.button = QPushButton(action)
        self.button.setObjectName("primary")
        self.button.clicked.connect(self.activated)
        self.button.setVisible(bool(action))
        layout.addWidget(self.button, 0, Qt.AlignHCenter)
        layout.addStretch()


class LocationBar(QFrame):
    open_requested = Signal()
    change_requested = Signal()

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setObjectName("locationBar")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, SPACE["lg"], 0, 0)
        row.setSpacing(SPACE["md"])
        row.addWidget(IconBadge("folder"))
        labels = QVBoxLayout()
        labels.setSpacing(SPACE["xs"])
        labels.addWidget(text_label("保存位置", role="caption"))
        self.location = ElidedLabel(str(path))
        labels.addWidget(self.location)
        row.addLayout(labels, 1)
        self.choose_button = QPushButton("更改位置")
        self.choose_button.setObjectName("link")
        self.choose_button.clicked.connect(self.change_requested)
        row.addWidget(self.choose_button)
        self.folder_button = QPushButton("打开文件夹")
        self.folder_button.clicked.connect(self.open_requested)
        row.addWidget(self.folder_button)

    def set_path(self, path):
        self.location.setText(str(path))


class ComposerFrame(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("composer")
        QApplication.instance().focusChanged.connect(self._focus_changed)

    def _focus_changed(self, previous, current):
        focused = current is not None and self.isAncestorOf(current)
        if self.property("focused") != focused:
            self.setProperty("focused", focused)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()


class RecentList(QListWidget):
    open_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.itemClicked.connect(self.open_requested.emit)
        self.setViewMode(QListWidget.IconMode)
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setFlow(QListWidget.LeftToRight)
        self.setWrapping(False)
        self.setUniformItemSizes(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        QTimer.singleShot(0, self.update_grid)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_grid()

    def update_grid(self):
        cell = max(1, self.viewport().width() // 3)
        cover_width = max(1, cell - HOME["tile_gap"])
        height = round(cover_width * 9 / 16) + HOME["tile_caption"] + HOME["tile_inset"] * 2
        size = QSize(cell, height)
        if self.gridSize() != size:
            self.setGridSize(size)
        if self.height() != height + HOME["tile_inset"]:
            self.setFixedHeight(height + HOME["tile_inset"])

    def keyPressEvent(self, event):
        if event.key() in {Qt.Key_Return, Qt.Key_Enter} and self.currentItem():
            self.open_requested.emit(self.currentItem())
            event.accept()
        else:
            super().keyPressEvent(event)


class RecentDelegate(QStyledItemDelegate):
    Row = Qt.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmaps = OrderedDict()
        self.thumbnail_provider = None

    def sizeHint(self, option, index):
        return self.parent().gridSize()

    def paint(self, painter, option, index):
        item = index.data(self.Row)
        if not item:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = option.rect
        inset = HOME["tile_inset"]
        gap = HOME["tile_gap"] // 2
        picture = QRect(rect.left() + gap, rect.top() + inset,
                        max(1, rect.width() - gap * 2), 1)
        picture.setHeight(round(picture.width() * 9 / 16))
        clip = QPainterPath()
        clip.addRoundedRect(picture, HOME["tile_radius"], HOME["tile_radius"])
        painter.setClipPath(clip)
        painter.fillRect(picture, QColor(COLORS["thumb"]))
        path = item.get("thumb") or ""
        if not self.thumbnail_provider and path and path not in self.pixmaps:
            self.pixmaps[path] = QPixmap(path)
            if len(self.pixmaps) > 32:
                self.pixmaps.popitem(last=False)
        pixmap = self.thumbnail_provider(item) if self.thumbnail_provider else self.pixmaps.get(path)
        if pixmap and not pixmap.isNull():
            painter.drawPixmap(picture, pixmap)
        else:
            mark = QRect(0, 0, METRICS["nav_icon"], METRICS["nav_icon"])
            mark.moveCenter(picture.center())
            icon("play", COLORS["muted"]).paint(painter, mark)
        font = option.font
        font.setPixelSize(METRICS["caption"])
        painter.setFont(font)
        duration = clock_text(item["duration"]) if item["duration"] else "图文"
        width = painter.fontMetrics().horizontalAdvance(duration) + SPACE["md"]
        badge = QRect(picture.right() - width - SPACE["sm"], picture.bottom() - SPACE["xxl"] - SPACE["sm"],
                      width, SPACE["xxl"])
        overlay = QColor(COLORS["overlay"])
        overlay.setAlpha(190)
        painter.setPen(Qt.NoPen)
        painter.setBrush(overlay)
        painter.drawRoundedRect(badge, SPACE["xs"], SPACE["xs"])
        painter.setPen(QColor(COLORS["white"]))
        painter.drawText(badge, Qt.AlignCenter, duration)
        if option.state & (QStyle.State_MouseOver | QStyle.State_Selected):
            play = QRect(0, 0, SPACE["page"], SPACE["page"])
            play.moveCenter(picture.center())
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(COLORS["white"]))
            painter.drawEllipse(play)
            icon("play", COLORS["text"]).paint(painter, play.adjusted(8, 8, -8, -8))
        painter.setClipping(False)
        if option.state & QStyle.State_HasFocus:
            painter.setPen(QColor(COLORS["text"]))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(picture.adjusted(-2, -2, 2, 2), HOME["tile_radius"], HOME["tile_radius"])
        font.setPixelSize(METRICS["body"])
        painter.setFont(font)
        painter.setPen(QColor(COLORS["text"]))
        title = QRect(picture.left(), picture.bottom() + SPACE["sm"], picture.width(), SPACE["xxl"])
        painter.drawText(title, Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(item["title"], Qt.ElideRight, title.width()))
        painter.restore()


def clock_text(value):
    seconds = max(0, round(value or 0))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}" if seconds >= 3600 else f"{seconds // 60:02d}:{seconds % 60:02d}"


def size_text(value):
    value = max(0, int(value or 0))
    return f"{value / 1024 ** 3:.2f} GB" if value >= 1024 ** 3 else f"{value / 1024 ** 2:.1f} MB"


class PasteLinkEdit(QLineEdit):
    pasted = Signal(str)

    def paste(self):
        # Clipboard is read only after an explicit paste gesture/button.
        text = QApplication.clipboard().text().strip()
        self.setText(text)
        self.pasted.emit(text)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Paste):
            self.paste()
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        action = menu.addAction("撤销", self.undo)
        action.setEnabled(self.isUndoAvailable())
        action = menu.addAction("重做", self.redo)
        action.setEnabled(self.isRedoAvailable())
        menu.addSeparator()
        action = menu.addAction("剪切", self.cut)
        action.setEnabled(self.hasSelectedText())
        action = menu.addAction("复制", self.copy)
        action.setEnabled(self.hasSelectedText())
        action = menu.addAction("粘贴", self.paste)
        action.setObjectName("pasteLink")
        action.setEnabled(QApplication.clipboard().mimeData().hasText())
        action = menu.addAction("删除", self.del_)
        action.setEnabled(self.hasSelectedText())
        menu.addSeparator()
        menu.addAction("全选", self.selectAll)
        menu.exec(event.globalPos())


class LoginSourceComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("登录来源")

    def wheelEvent(self, event):
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()
