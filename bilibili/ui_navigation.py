"""Collapsible desktop navigation and a search overlay independent of the library."""
from PySide6.QtCore import QElapsedTimer, QEvent, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPen
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFrame, QHBoxLayout, QLineEdit,
    QListWidget, QListWidgetItem, QSizePolicy, QStackedWidget, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QToolButton, QVBoxLayout)

from ui_theme import COLORS, DIALOG, RAIL, SPACE, icon
from ui_widgets import text_label


NAVIGATION_ITEMS = (
    (0, "下载", "compose"),
    (3, "提取 MP3", "audio"),
    (1, "我的视频", "library-stack"),
    (2, "软件更新", "nav-update"),
)


class FadingTitleDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        view = self.parent()
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        title, styled.text = styled.text, ""
        view.style().drawControl(QStyle.CE_ItemViewItem, styled, painter, view)
        area = QRectF(option.rect).adjusted(SPACE["md"], 0, -SPACE["md"], 0)
        width = option.fontMetrics.horizontalAdvance(title)
        offset = view.title_offset(width, area.width())
        painter.save()
        painter.setClipRect(area)
        painter.setFont(option.font)
        if width > area.width():
            fade = min(RAIL["title_fade"] / max(area.width(), 1), .25)
            gradient = QLinearGradient(area.left(), 0, area.right(), 0)
            color, clear = QColor(COLORS["text"]), QColor(COLORS["text"])
            clear.setAlpha(0)
            gradient.setColorAt(0, clear if view.clock.elapsed() > RAIL["title_pause_ms"] else color)
            gradient.setColorAt(fade, color)
            gradient.setColorAt(1 - fade, color)
            gradient.setColorAt(1, clear)
            painter.setPen(QPen(QBrush(gradient), 1))
        else:
            painter.setPen(QColor(COLORS["text"]))
        painter.drawText(QRectF(area.left() - offset, area.top(), max(width, area.width()) + 1, area.height()),
                         Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine, title)
        if width > area.width():
            # A second copy enters from the right as the first leaves the left.
            painter.drawText(QRectF(area.left() - offset + width + RAIL["title_gap"], area.top(), width + 1, area.height()),
                             Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine, title)
        painter.restore()


class MediaTitleList(QListWidget):
    open_requested = Signal(object)

    def __init__(self, *, role, row_height, parent=None):
        super().__init__(parent)
        self.setObjectName(role)
        self.row_height = row_height
        self.animated = role == "sidebarRecent"
        self.signature = None
        self.clock = QElapsedTimer()
        self.clock.start()
        self.animation = QTimer(self)
        self.animation.setInterval(RAIL["animation_ms"])
        self.animation.timeout.connect(self.viewport().update)
        if self.animated:
            self.setItemDelegate(FadingTitleDelegate(self))
        self.setTextElideMode(Qt.ElideRight)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setMouseTracking(True)
        self.itemClicked.connect(self.open_item)

    def set_rows(self, rows):
        signature = [(row["id"], row["title"]) for row in rows]
        if signature != self.signature:
            self.signature = signature
            self.clock.restart()
        selected = self.currentItem().data(Qt.UserRole)["id"] if self.currentItem() else None
        self.clear()
        for row in rows:
            item = QListWidgetItem(row["title"])
            item.setData(Qt.UserRole, row)
            item.setToolTip(row["title"])
            item.setSizeHint(QSize(0, self.row_height))
            self.addItem(item)
            if row["id"] == selected:
                self.setCurrentItem(item)
        self.sync_animation()

    def title_offset(self, text_width, available):
        if text_width <= available:
            return 0
        elapsed = max(0, self.clock.elapsed() - RAIL["title_pause_ms"])
        return elapsed * RAIL["title_speed"] / 1000 % (text_width + RAIL["title_gap"])

    def sync_animation(self):
        width = self.viewport().width() - 2 * SPACE["md"]
        needed = self.animated and self.isVisible() and any(
            self.fontMetrics().horizontalAdvance(self.item(number).text()) > width for number in range(self.count()))
        if needed and not self.animation.isActive():
            self.animation.start()
        elif not needed:
            self.animation.stop()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.sync_animation)

    def hideEvent(self, event):
        self.animation.stop()
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.clock.restart()
        self.sync_animation()

    def open_item(self, item):
        if item:
            self.open_requested.emit(item.data(Qt.UserRole))

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.open_item(self.currentItem())
            event.accept()
        else:
            super().keyPressEvent(event)


class NavigationSidebar(QFrame):
    expanded_changed = Signal(bool)
    page_requested = Signal(int)
    search_requested = Signal()
    settings_requested = Signal()
    open_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("iconRail")
        self.expanded = False
        self.rows = []
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(RAIL["inset"], RAIL["top"], RAIL["inset"], RAIL["bottom"])
        self.body.setSpacing(RAIL["gap"])
        self.header = QHBoxLayout()
        self.header.setContentsMargins(0, 0, 0, 0)
        self.header.setSpacing(SPACE["xs"])
        self.logo = self.action("app", "展开侧栏", size=RAIL["button_size"], image_size=RAIL["logo_size"])
        self.logo.setObjectName("menuButton")
        self.logo.clicked.connect(self.toggle)
        self.header.addWidget(self.logo)
        self.brand = text_label("视频下载器", role="brand")
        self.header.addWidget(self.brand, 1)
        self.header_search = self.action("search", "搜索作品")
        self.header_search.clicked.connect(self.search_requested)
        self.header.addWidget(self.header_search)
        self.collapse_button = self.action("sidebar", "收起侧栏")
        self.collapse_button.clicked.connect(self.toggle)
        self.header.addWidget(self.collapse_button)
        self.body.addLayout(self.header)
        self.body.addSpacing(RAIL["brand_gap"])
        self.navigation = {}
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.navigation_titles = {page: title for page, title, _ in NAVIGATION_ITEMS}
        for page, title, image in NAVIGATION_ITEMS:
            button = self.action(image, title, size=RAIL["button_size"], image_size=RAIL["icon_size"])
            button.setObjectName("railButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, page=page: self.page_requested.emit(page))
            self.navigation[page] = button
            self.group.addButton(button, page)
            self.body.addWidget(button)
        self.recent_group = QFrame()
        recent_layout = QVBoxLayout(self.recent_group)
        recent_layout.setContentsMargins(0, RAIL["recent_gap"], 0, 0)
        recent_layout.setSpacing(SPACE["sm"])
        recent_layout.addWidget(text_label("最近", role="navCaption"))
        self.recent = MediaTitleList(role="sidebarRecent", row_height=RAIL["recent_row"])
        self.recent.setAccessibleName("最近作品")
        self.recent.open_requested.connect(self.open_requested)
        recent_layout.addWidget(self.recent, 1)
        self.body.addWidget(self.recent_group, 1)
        self.body.addStretch()
        self.account_button = self.action("account", "设置与账号", size=RAIL["account_size"], image_size=RAIL["icon_size"])
        self.account_button.setObjectName("accountButton")
        self.account_button.clicked.connect(self.settings_requested)
        self.body.addWidget(self.account_button, 0, Qt.AlignHCenter)
        self.set_expanded(False)

    def action(self, image, label, *, size=None, image_size=None):
        button = QToolButton()
        button.setObjectName("sidebarAction")
        button.setIcon(icon(image, COLORS["text"]) if image != "app" else icon("app"))
        image_size = image_size or RAIL["expanded_icon"]
        button.setIconSize(QSize(image_size, image_size))
        button.setFixedSize(size or RAIL["header_action"], size or RAIL["header_action"])
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.setCursor(Qt.PointingHandCursor)
        return button

    def toggle(self):
        self.set_expanded(not self.expanded)

    def set_expanded(self, expanded):
        self.expanded = expanded
        self.setMinimumWidth(RAIL["expanded_min"] if expanded else RAIL["width"])
        self.setMaximumWidth(RAIL["expanded_max"] if expanded else RAIL["width"])
        for widget in (self.brand, self.header_search, self.collapse_button):
            widget.setVisible(expanded)
        # The expanded header contains the brand, search and collapse controls.
        self.logo.setVisible(not expanded)
        self.recent_group.setVisible(expanded and bool(self.rows))
        self.body.setStretch(self.body.indexOf(self.recent_group), 1 if expanded and self.rows else 0)
        self.body.setStretch(self.body.count() - 2, 0 if expanded and self.rows else 1)
        for page, button in self.navigation.items():
            button.setObjectName("sidebarNav" if expanded else "railButton")
            button.setText(self.navigation_titles[page] if expanded else "")
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if expanded else Qt.ToolButtonIconOnly)
            button.setIconSize(QSize(RAIL["expanded_icon"] if expanded else RAIL["icon_size"],
                                     RAIL["expanded_icon"] if expanded else RAIL["icon_size"]))
            button.setFixedHeight(RAIL["expanded_row"] if expanded else RAIL["button_size"])
            button.setMinimumWidth(0 if expanded else RAIL["button_size"])
            button.setMaximumWidth(16777215 if expanded else RAIL["button_size"])
            button.setSizePolicy(QSizePolicy.Expanding if expanded else QSizePolicy.Fixed, QSizePolicy.Fixed)
            button.style().unpolish(button)
            button.style().polish(button)
        account = self.account_button
        account.setObjectName("sidebarAccount" if expanded else "accountButton")
        account.setText("设置与账号" if expanded else "")
        account.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if expanded else Qt.ToolButtonIconOnly)
        account.setFixedHeight(RAIL["expanded_row"] if expanded else RAIL["account_size"])
        account.setMinimumWidth(0 if expanded else RAIL["account_size"])
        account.setMaximumWidth(16777215 if expanded else RAIL["account_size"])
        self.body.setAlignment(account, Qt.Alignment() if expanded else Qt.AlignHCenter)
        account.style().unpolish(account)
        account.style().polish(account)
        self.setAccessibleName("导航侧栏，已展开" if expanded else "导航侧栏，已收起")
        if self.isVisible():
            (self.collapse_button if expanded else self.logo).setFocus(Qt.OtherFocusReason)
        self.expanded_changed.emit(expanded)

    def set_page(self, page):
        self.navigation[page].setChecked(True)

    def set_rows(self, rows):
        self.rows = list(rows[:RAIL["recent_limit"]])
        self.recent.set_rows(self.rows)
        self.recent_group.setVisible(self.expanded and bool(self.rows))
        self.body.setStretch(self.body.indexOf(self.recent_group), 1 if self.expanded and self.rows else 0)
        self.body.setStretch(self.body.count() - 2, 0 if self.expanded and self.rows else 1)


class MediaSearchDialog(QDialog):
    open_requested = Signal(object)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.rows = []
        self.setWindowTitle("搜索作品")
        self.setWindowModality(Qt.WindowModal)
        self.resize(DIALOG["search_width"], DIALOG["search_height"])
        self.setMinimumSize(DIALOG["search_min_width"], DIALOG["search_min_height"])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        layout.setSpacing(SPACE["lg"])
        header = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索作品")
        self.search.setAccessibleName("搜索作品名称")
        self.search.installEventFilter(self)
        self.search.addAction(icon("search", COLORS["muted"]), QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        header.addWidget(self.search, 1)
        self.close_button = QToolButton()
        self.close_button.setObjectName("sidebarAction")
        self.close_button.setIcon(icon("close", COLORS["text"]))
        self.close_button.setIconSize(QSize(RAIL["expanded_icon"], RAIL["expanded_icon"]))
        self.close_button.setFixedSize(RAIL["header_action"], RAIL["header_action"])
        self.close_button.setToolTip("关闭搜索")
        self.close_button.setAccessibleName("关闭搜索")
        self.close_button.clicked.connect(self.reject)
        header.addWidget(self.close_button)
        layout.addLayout(header)
        self.caption = text_label("最近", role="navCaption")
        layout.addWidget(self.caption)
        self.results = MediaTitleList(role="searchResults", row_height=DIALOG["search_row"])
        self.results.setAccessibleName("搜索结果，按回车打开作品")
        self.results.open_requested.connect(self.open_result)
        self.empty = text_label("暂无作品", role="muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.results)
        self.stack.addWidget(self.empty)
        layout.addWidget(self.stack, 1)
        self.search.textChanged.connect(self.filter)
        self.search.returnPressed.connect(lambda: self.results.open_item(self.results.currentItem()))
        self.refresh()

    def refresh(self, rows=None):
        self.rows = list(rows if rows is not None else self.store.rows())
        self.filter()

    def filter(self, *_):
        query = self.search.text().strip().casefold()
        matches = [row for row in self.rows if query in row["title"].casefold()]
        self.results.set_rows(matches)
        if matches:
            self.results.setCurrentRow(0)
        self.caption.setText("搜索结果" if query else "最近")
        self.stack.setCurrentWidget(self.results if matches else self.empty)
        self.empty.setText("未找到作品" if query else "暂无作品")

    def open_result(self, item):
        self.accept()
        self.open_requested.emit(item)

    def eventFilter(self, watched, event):
        if watched is self.search and event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Up, Qt.Key_Down):
            if self.results.count():
                step = 1 if event.key() == Qt.Key_Down else -1
                row = max(0, min(self.results.count() - 1, self.results.currentRow() + step))
                self.results.setCurrentRow(row)
                self.results.scrollToItem(self.results.currentItem())
            return True
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        self.search.setFocus(Qt.ShortcutFocusReason)
        self.search.selectAll()
