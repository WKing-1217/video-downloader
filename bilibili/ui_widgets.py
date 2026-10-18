"""Native controls with explicit user intent for paste-to-download."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QLabel, QLineEdit, QMenu, QVBoxLayout


def text_label(text="", *, role=None, wrap=False):
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(wrap)
    if role:
        label.setObjectName(role)
    return label


def panel():
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(14)
    return frame, layout


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
        action = menu.addAction("粘贴并下载", self.paste)
        action.setObjectName("pasteDownload")
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
