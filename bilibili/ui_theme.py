"""Shared Windows v2 type, spacing, colors and vector icons."""
from pathlib import Path
from PySide6.QtGui import QIcon
from PySide6.QtSvg import QSvgRenderer  # Load SVG support before icon/QSS plugin resolution.

ROOT = Path(__file__).resolve().parent
COLORS = {"background": "#f5f6fa", "surface": "#ffffff", "text": "#202533",
          "muted": "#697386", "accent": "#dc4775", "border": "#e2e5ed",
          "hover": "#eef0f6", "tint": "#fceaf0", "danger": "#b83255"}
METRICS = {"sidebar": 158, "page_inset": 26, "gap": 16, "body": 15,
           "title": 23, "radius": 10, "control_height": 38, "card_width": 246, "card_height": 234}


def icon(name):
    return QIcon(str(ROOT / "assets" / (name + ".svg")))


def stylesheet():
    return """
    QWidget {font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: %(body)spx; color: %(text)s;}
    QMainWindow, QWidget#windowRoot, QStackedWidget {background: %(background)s;}
    QFrame#sidebar {background: %(surface)s; border-right: 1px solid %(border)s;}
    QLabel#brand {font-size: 16px; font-weight: 600;}
    QLabel#pageTitle {font-size: %(title)spx; font-weight: 600;}
    QLabel#sectionTitle {font-size: 17px; font-weight: 600;}
    QLabel#muted {color: %(muted)s; font-size: 13px;}
    QLabel#error {color: %(danger)s;}
    QFrame#panel {background: %(surface)s; border: 1px solid %(border)s; border-radius: %(radius)spx;}
    QPushButton, QToolButton {background: %(surface)s; border: 1px solid %(border)s; border-radius: 8px;
        padding: 8px 13px; min-height: 20px;}
    QPushButton:hover, QToolButton:hover {background: %(hover)s;}
    QToolButton::menu-indicator {image: none;}
    QPushButton:pressed, QToolButton:pressed {background: #e3e6ee;}
    QPushButton:disabled, QToolButton:disabled {color: #a0a6b2; background: #eff0f4;}
    QPushButton#primary {background: %(accent)s; color: white; border-color: %(accent)s; font-weight: 600;}
    QPushButton#primary:hover {background: #c83765;}
    QPushButton#primary:pressed {background: #b82c5a;}
    QPushButton#primary:disabled {background: #cfabb8; border-color: #cfabb8;}
    QPushButton#nav {border: none; background: transparent; text-align: left; padding: 12px 14px;}
    QPushButton#nav:hover {background: %(hover)s;}
    QPushButton#nav:checked {background: %(tint)s; color: %(accent)s; font-weight: 600;}
    QPushButton#link {background: transparent; border: none; color: %(accent)s; padding: 5px 2px;}
    QPushButton#link:hover {color: #b82c5a;}
    QLineEdit, QComboBox, QPlainTextEdit, QTextBrowser, QListWidget#queue {
        background: %(surface)s; border: 1px solid %(border)s; border-radius: 8px; padding: 9px 12px;
        selection-background-color: %(accent)s;}
    QLineEdit:focus, QComboBox:focus {border-color: %(accent)s;}
    QLineEdit#linkInput {font-size: 16px; padding: 13px 14px;}
    QComboBox {padding-right: 42px;}
    QComboBox::drop-down {subcontrol-origin: padding; subcontrol-position: top right;
        width: 36px; border: none;}
    QComboBox::down-arrow {image: url("%(chevron)s"); width: 17px; height: 17px;}
    QComboBox QAbstractItemView {background: %(surface)s; selection-background-color: %(accent)s; outline: none;}
    QProgressBar {border: none; border-radius: 4px; background: #e4e7ee; min-height: 8px; max-height: 8px;}
    QProgressBar::chunk {background: %(accent)s; border-radius: 4px;}
    QCheckBox {spacing: 8px;}
    QSlider::groove:horizontal {height: 5px; background: #dfe3ec; border-radius: 2px;}
    QSlider::sub-page:horizontal {background: %(accent)s; border-radius: 2px;}
    QSlider::handle:horizontal {width: 13px; margin: -5px 0; border-radius: 6px; background: %(accent)s;}
    QListView#libraryGrid {border: none; background: transparent; outline: none;}
    QScrollArea {border: none; background: transparent;}
    QScrollBar:vertical {background: transparent; width: 9px; margin: 0;}
    QScrollBar::handle:vertical {background: #cbd0dc; border-radius: 4px; min-height: 32px;}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {height: 0;}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {background: transparent;}
    QMenu {background: white; border: 1px solid %(border)s; padding: 5px;}
    QMenu::item {padding: 8px 24px; border-radius: 4px;}
    QMenu::item:selected {background: %(tint)s; color: %(accent)s;}
    """ % {**COLORS, **METRICS, "chevron": (ROOT / "assets/chevron-down.svg").as_posix()}
