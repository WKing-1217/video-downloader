"""The desktop design system: semantic tokens, native controls and SVG icons."""
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent
COLORS = {
    "background": "#fbfbfb", "sidebar_background": "#fbfbfb", "surface": "#ffffff",
    "text": "#171717", "muted": "#696969", "subtle": "#757575",
    "accent": "#171717", "accent_hover": "#333333", "accent_pressed": "#000000",
    "border": "#e6e6e6", "hover": "#f2f2f2", "pressed": "#e8e8e8",
    "tint": "#f0f0f0", "danger": "#262626", "danger_tint": "#f0f0f0",
    "success": "#262626", "success_tint": "#f0f0f0",
    "disabled": "#969696", "disabled_surface": "#f1f1f1",
    "progress_track": "#eaeaea", "thumb": "#eeeeee", "video": "#151515",
    "overlay": "#202020", "white": "#ffffff",
}
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 20, "xxl": 24, "page": 32}
METRICS = {
    "sidebar": 72, "page_inset": 40, "gap": SPACE["lg"],
    "body": 14, "caption": 12, "title": 22, "section": 16, "display": 28,
    "radius": 12, "control_radius": 8, "control_height": 40, "input_height": 48,
    "card_width": 280, "card_height": 242, "card_inset": 6, "card_footer": 102,
    "nav_icon": 20, "badge_icon": 40, "small_icon": 16,
    "default_width": 1120, "default_height": 780, "min_width": 860, "min_height": 620,
    "recent_row": 72, "recent_thumb_width": 76, "recent_thumb_height": 44,
}
HOME = {"content_width": 780, "greeting_size": 26, "greeting_gap": 24,
        "preview_gap": 28, "composer_height": 64, "composer_radius": 24,
        "composer_inset": 10, "action_size": 42, "action_radius": 21,
        "menu_size": 44, "logo_size": 28, "shadow_blur": 20, "shadow_offset": 2,
        "shadow_alpha": 10, "tile_gap": 16,
        "tile_radius": 10, "tile_caption": 32, "tile_inset": 4}
RAIL = {"width": METRICS["sidebar"], "inset": 12, "top": 16, "bottom": 16,
        "button_size": 48, "icon_size": 23, "logo_size": 36, "gap": 4,
        "brand_gap": 20, "account_size": 40, "account_radius": 20, "header_height": 64,
        "expanded_width": 280, "expanded_row": 44, "header_action": 32,
        "expanded_icon": 20, "recent_limit": 12, "recent_gap": 28, "recent_row": 40}
DIALOG = {"settings_width": 820, "settings_height": 680, "settings_min_width": 700,
          "settings_min_height": 560, "inset": 32, "search_width": 640, "search_height": 480,
          "search_min_width": 480, "search_min_height": 320, "search_row": 48}


@lru_cache(maxsize=96)
def icon(name, color=None):
    path = ROOT / "assets" / (name + ".svg")
    if color is None:
        return QIcon(str(path))
    source = path.read_text(encoding="utf-8").replace("#697386", color).replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(source.encode("utf-8")))
    pixmap = QPixmap(96, 96)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def stylesheet():
    values = {**COLORS, **METRICS, **HOME,
              # QSS sizes exclude the one-pixel border on both sides.
              "rail_button_size": RAIL["button_size"] - 2, "rail_account_size": RAIL["account_size"] - 2,
              "rail_account_radius": RAIL["account_radius"],
              "sidebar_action_size": RAIL["header_action"] - 2,
              "sidebar_row_height": RAIL["expanded_row"] - 2,
              "chevron": (ROOT / "assets/chevron-down.svg").as_posix(),
              "checkmark": (ROOT / "assets/checkmark.svg").as_posix()}
    return """
    QWidget {font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: %(body)spx; color: %(text)s;}
    QMainWindow, QDialog, QWidget#windowRoot, QWidget#pageCanvas {background: %(background)s;}
    QStackedWidget {background: transparent;}
    QFrame#sidebar {background: %(sidebar_background)s; border-right: 1px solid %(border)s;}
    QFrame#iconRail {background: %(background)s; border: none; border-right: 1px solid %(border)s;}
    QLabel {background: transparent;}
    QLabel#brand {font-size: 16px; font-weight: 600;}
    QLabel#pageTitle {font-size: %(title)spx; font-weight: 600;}
    QLabel#greeting {font-size: %(greeting_size)spx; font-weight: 500;}
    QLabel#pageSubtitle {color: %(muted)s; font-size: 13px;}
    QLabel#sectionTitle {font-size: %(section)spx; font-weight: 600;}
    QLabel#taskTitle {font-size: 16px; font-weight: 600;}
    QLabel#display {font-size: %(display)spx; font-weight: 600;}
    QLabel#muted {color: %(muted)s; font-size: 13px;}
    QLabel#caption, QLabel#navCaption {color: %(muted)s; font-size: %(caption)spx;}
    QLabel#navCaption {padding: 0 12px;}
    QLabel#error {color: %(danger)s; background: %(danger_tint)s; border-radius: 6px; padding: 10px 12px;}
    QLabel#platform {color: %(muted)s; background: %(hover)s; border-radius: 5px; padding: 4px 8px; font-size: 12px;}
    QLabel#statusBadge {color: %(muted)s; background: %(hover)s; border-radius: 5px; padding: 4px 9px; font-size: 12px;}
    QLabel#statusBadge[tone="active"] {color: %(accent_hover)s; background: %(tint)s;}
    QLabel#statusBadge[tone="success"] {color: %(success)s; background: %(success_tint)s;}
    QLabel#statusBadge[tone="danger"] {color: %(danger)s; background: %(danger_tint)s;}
    QLabel#iconBadge {background: %(hover)s; border-radius: 10px;}
    QLabel#iconBadge[tone="active"] {background: %(tint)s;}
    QLabel#iconBadge[tone="success"] {background: %(success_tint)s;}
    QLabel#iconBadge[tone="danger"] {background: %(danger_tint)s;}
    QFrame#panel, QFrame#taskPanel {background: %(surface)s; border: 1px solid %(border)s; border-radius: %(radius)spx;}
    QFrame#composer {background: %(surface)s; border: 1px solid %(border)s; border-radius: %(composer_radius)spx;}
    QFrame#composer[focused="true"] {border-color: #888888;}
    QFrame#locationBar {background: transparent; border: none; border-top: 1px solid %(border)s;}
    QFrame#divider {background: %(border)s; border: none; max-height: 1px;}
    QPushButton, QToolButton {background: %(surface)s; border: 1px solid %(border)s; border-radius: %(control_radius)spx;
        padding: 9px 14px; min-height: 20px;}
    QPushButton:hover, QToolButton:hover {background: %(hover)s; border-color: #dadada;}
    QPushButton:pressed, QToolButton:pressed {background: %(pressed)s;}
    QPushButton:focus, QToolButton:focus {border-color: %(accent)s;}
    QToolButton::menu-indicator {image: none;}
    QLineEdit QToolButton {background: transparent; border: none; border-radius: 0; padding: 0; min-height: 0;}
    QPushButton:disabled, QToolButton:disabled {color: %(disabled)s; background: %(disabled_surface)s; border-color: %(border)s;}
    QPushButton#primary {background: %(accent)s; color: white; border-color: %(accent)s; font-weight: 600;}
    QPushButton#primary:hover {background: %(accent_hover)s; border-color: %(accent_hover)s;}
    QPushButton#primary:pressed {background: %(accent_pressed)s;}
    QPushButton#primary:focus {border: 2px solid %(accent_pressed)s; padding: 8px 13px;}
    QPushButton#primary:disabled {background: #aaaaaa; border-color: #aaaaaa;}
    QPushButton#sendAction {background: %(accent)s; border: 1px solid %(accent)s; border-radius: %(action_radius)spx; padding: 0; min-height: 0;}
    QPushButton#sendAction:hover {background: %(accent_hover)s;}
    QPushButton#sendAction:focus {border: 2px solid #777777;}
    QPushButton#sendAction:pressed {background: %(accent_pressed)s;}
    QToolButton#pasteAction, QToolButton#menuButton {background: transparent; border: 1px solid transparent; padding: 0; min-height: 0; border-radius: 10px;}
    QToolButton#pasteAction:hover, QToolButton#menuButton:hover {background: %(hover)s;}
    QToolButton#pasteAction:focus, QToolButton#menuButton:focus {border-color: #888888;}
    QToolButton#menuButton {min-height: %(rail_button_size)spx; max-height: %(rail_button_size)spx;
        min-width: %(rail_button_size)spx; max-width: %(rail_button_size)spx;}
    QToolButton#railButton {background: transparent; border: 1px solid transparent; border-radius: 10px; padding: 0;
        min-height: %(rail_button_size)spx; max-height: %(rail_button_size)spx;
        min-width: %(rail_button_size)spx; max-width: %(rail_button_size)spx;}
    QToolButton#railButton:hover, QToolButton#railButton:checked {background: %(hover)s;}
    QToolButton#railButton:pressed {background: %(pressed)s;}
    QToolButton#railButton:focus {border-color: #888888;}
    QToolButton#accountButton {background: %(hover)s; border: 1px solid transparent; border-radius: %(rail_account_radius)spx; padding: 0;
        min-height: %(rail_account_size)spx; max-height: %(rail_account_size)spx;
        min-width: %(rail_account_size)spx; max-width: %(rail_account_size)spx;}
    QToolButton#accountButton:hover {background: %(pressed)s;}
    QToolButton#accountButton:focus {border-color: #888888;}
    QToolButton#sidebarAction {background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 0;
        min-width: %(sidebar_action_size)spx; max-width: %(sidebar_action_size)spx;
        min-height: %(sidebar_action_size)spx; max-height: %(sidebar_action_size)spx;}
    QToolButton#sidebarAction:hover {background: %(hover)s;}
    QToolButton#sidebarAction:focus {border-color: #888888;}
    QToolButton#sidebarNav, QToolButton#sidebarAccount {background: transparent; border: 1px solid transparent;
        border-radius: 8px; padding: 0 12px; text-align: left;
        min-height: %(sidebar_row_height)spx; max-height: %(sidebar_row_height)spx;}
    QToolButton#sidebarNav:hover, QToolButton#sidebarNav:checked, QToolButton#sidebarAccount:hover {background: %(hover)s;}
    QToolButton#sidebarNav:focus, QToolButton#sidebarAccount:focus {border-color: #888888;}
    QListWidget#sidebarRecent, QListWidget#searchResults {background: transparent; border: none; outline: none; padding: 0;}
    QListWidget#sidebarRecent::item, QListWidget#searchResults::item {border: 1px solid transparent; border-radius: 8px; padding: 0 12px;}
    QListWidget#sidebarRecent::item:hover, QListWidget#searchResults::item:hover {background: %(hover)s;}
    QListWidget#sidebarRecent::item:selected, QListWidget#searchResults::item:selected {background: %(tint)s; color: %(text)s;}
    QListWidget#sidebarRecent::item:focus, QListWidget#searchResults::item:focus {border-color: #888888;}
    QPushButton#nav {border: 1px solid transparent; background: transparent; text-align: left; padding: 11px 12px;}
    QPushButton#nav:hover {background: %(pressed)s;}
    QPushButton#nav:checked {background: %(surface)s; color: %(accent)s; border-color: %(border)s; font-weight: 600;}
    QPushButton#nav:focus {border-color: %(accent)s;}
    QPushButton#link {background: transparent; border: 1px solid transparent; color: %(accent)s; padding: 6px 4px;}
    QPushButton#link:hover {background: %(tint)s; color: %(accent_hover)s;}
    QPushButton#link:focus {border-color: %(accent)s;}
    QToolButton#settings {background: transparent; padding: 9px;}
    QLineEdit, QComboBox, QPlainTextEdit, QTextBrowser {
        background: %(surface)s; border: 1px solid %(border)s; border-radius: %(control_radius)spx; padding: 9px 12px;
        selection-background-color: %(accent)s; selection-color: white;}
    QLineEdit:hover, QComboBox:hover {border-color: #cecece;}
    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextBrowser:focus {border-color: %(accent)s;}
    QLineEdit#linkInput {font-size: 16px; padding: 8px 10px; background: transparent; border: none;}
    QLineEdit#searchInput {padding-left: 6px;}
    QTextBrowser#releaseNotes {border: none; border-radius: 0; padding: 0;}
    QLabel#galleryPreview {background: %(video)s; border-radius: %(control_radius)spx; color: white;}
    QComboBox {padding-right: 38px;}
    QComboBox::drop-down {subcontrol-origin: padding; subcontrol-position: top right; width: 30px; border: none;}
    QComboBox::down-arrow {image: url("%(chevron)s"); width: 16px; height: 16px;}
    QComboBox QAbstractItemView {background: %(surface)s; selection-background-color: %(tint)s; selection-color: %(accent_hover)s;
        border: 1px solid %(border)s; padding: 5px; outline: none;}
    QProgressBar {border: none; border-radius: 3px; background: %(progress_track)s; min-height: 6px; max-height: 6px;}
    QProgressBar::chunk {background: %(accent)s; border-radius: 3px;}
    QProgressBar[tone="success"]::chunk {background: %(success)s;}
    QProgressBar[tone="danger"]::chunk {background: %(danger)s;}
    QCheckBox {spacing: 10px;}
    QCheckBox::indicator {width: 17px; height: 17px; border: 1px solid #bfbfbf; border-radius: 4px; background: white;}
    QCheckBox::indicator:checked {background: %(accent)s; border-color: %(accent)s; image: url("%(checkmark)s");}
    QCheckBox::indicator:focus {border: 2px solid %(accent)s;}
    QCheckBox::indicator:disabled {background: %(disabled_surface)s; border-color: %(border)s;}
    QSlider::groove:horizontal {height: 4px; background: %(progress_track)s; border-radius: 2px;}
    QSlider::sub-page:horizontal {background: %(accent)s; border-radius: 2px;}
    QSlider::handle:horizontal {width: 14px; margin: -5px 0; border-radius: 7px; background: %(accent)s;}
    QSlider::handle:horizontal:focus {border: 2px solid %(accent_pressed)s;}
    QListView#libraryGrid, QListWidget#recentList {border: none; background: transparent; outline: none; padding: 0;}
    QListWidget#assetList {border: 1px solid %(border)s; border-radius: 8px; background: %(surface)s; padding: 6px;}
    QListWidget#assetList::item {padding: 10px; border-radius: 5px;}
    QListWidget#assetList::item:selected {background: %(tint)s; color: %(accent)s;}
    QScrollArea {border: none; background: transparent;}
    QScrollBar:vertical {background: transparent; width: 8px; margin: 0;}
    QScrollBar::handle:vertical {background: #cdcdcd; border-radius: 4px; min-height: 32px;}
    QScrollBar::handle:vertical:hover {background: #b3b3b3;}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {height: 0;}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {background: transparent;}
    QMenu {background: %(surface)s; border: 1px solid %(border)s; padding: 5px;}
    QMenu::item {padding: 9px 24px; border-radius: 4px;}
    QMenu::item:selected {background: %(tint)s; color: %(accent_hover)s;}
    QToolTip {background: %(text)s; color: white; border: none; padding: 6px 9px;}
    """ % values
