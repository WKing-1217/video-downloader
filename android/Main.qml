import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    visible: true
    width: 420; height: 860
    title: "视频下载器"
    color: backgroundColor
    readonly property color backgroundColor: "#f5f7fa"
    readonly property color surface: "#ffffff"
    readonly property color ink: "#202d3d"
    readonly property color muted: "#596b80"
    readonly property color accent: "#45658a"
    readonly property color accentPressed: "#29425e"
    readonly property color borderColor: "#dce4ed"
    readonly property color selectedColor: "#dfe9f5"
    readonly property color disabledSurface: "#eaf0f5"
    readonly property color disabledAccent: "#91a3b8"
    readonly property color progressTrack: "#e2e9f1"
    // One layout owns all system insets. Header, pages and bottom navigation
    // are explicit siblings so framework padding cannot count the bars twice.
    topPadding: 0; bottomPadding: 0; leftPadding: 0; rightPadding: 0
    property real previewSafeTop: 0
    property real previewSafeBottom: 0
    property real previewSafeLeft: 0
    property real previewSafeRight: 0
    property bool previewKeyboardVisible: false
    readonly property int inset: width < 360 ? 16 : 24
    readonly property int headerHeight: 56
    readonly property int navigationHeight: 72
    readonly property int iconSize: 24
    readonly property int pageTitleSize: width < 360 ? 22 : 24
    readonly property int gap: 16
    readonly property int controlHeight: 48
    font.pixelSize: 16
    palette.text: ink
    palette.windowText: ink
    palette.highlight: selectedColor
    palette.highlightedText: ink

    component LineIcon: Canvas {
        property string kind: "arrow"
        property color stroke: window.ink
        implicitWidth: 24; implicitHeight: 24
        onKindChanged: requestPaint()
        onStrokeChanged: requestPaint()
        onPaint: {
            const c = getContext("2d")
            c.reset(); c.scale(width / 24, height / 24)
            c.strokeStyle = stroke; c.lineWidth = 1.7; c.lineCap = "round"; c.lineJoin = "round"
            c.beginPath()
            if (kind === "audio") {
                c.moveTo(10, 17); c.lineTo(10, 5); c.lineTo(20, 3); c.lineTo(20, 15)
                c.moveTo(10, 9); c.lineTo(20, 7)
                c.moveTo(10, 17); c.ellipse(4, 15, 6, 4)
                c.moveTo(20, 15); c.ellipse(14, 13, 6, 4)
            } else if (kind === "settings") {
                // Eight teeth communicate settings; the old crosshair meant location.
                for (let i = 0; i < 32; ++i) {
                    const r = (i % 4 === 0 || i % 4 === 3) ? 9.5 : 7.5
                    const angle = (i * 11.25 - 90) * Math.PI / 180
                    const x = 12 + r * Math.cos(angle), y = 12 + r * Math.sin(angle)
                    if (i === 0) c.moveTo(x, y); else c.lineTo(x, y)
                }
                c.closePath(); c.moveTo(15, 12); c.arc(12, 12, 3, 0, Math.PI * 2)
            } else if (kind === "library") {
                c.roundedRect(3, 4, 4, 16, 1, 1); c.roundedRect(9, 4, 4, 16, 1, 1)
                c.moveTo(15, 5); c.lineTo(19, 4); c.lineTo(22, 19); c.lineTo(18, 20); c.closePath()
            } else if (kind === "refresh") {
                c.arc(12, 12, 8, -Math.PI * 0.8, Math.PI * 0.8)
                c.moveTo(4, 6); c.lineTo(4, 2); c.lineTo(8, 2)
            } else if (kind === "trash") {
                c.moveTo(4, 6); c.lineTo(20, 6); c.moveTo(9, 3); c.lineTo(15, 3)
                c.moveTo(6, 6); c.lineTo(7, 21); c.lineTo(17, 21); c.lineTo(18, 6)
                c.moveTo(10, 10); c.lineTo(10, 17); c.moveTo(14, 10); c.lineTo(14, 17)
            } else if (kind === "paste") {
                c.roundedRect(6, 5, 12, 16, 2, 2); c.roundedRect(9, 2, 6, 5, 1, 1)
                c.moveTo(9, 11); c.lineTo(15, 11); c.moveTo(9, 15); c.lineTo(15, 15)
            } else if (kind === "download") {
                c.roundedRect(4, 3, 16, 18, 3, 3)
                c.moveTo(12, 6); c.lineTo(12, 15); c.moveTo(8, 11); c.lineTo(12, 15); c.lineTo(16, 11)
            } else {
                c.moveTo(12, 19); c.lineTo(12, 5); c.moveTo(6, 11); c.lineTo(12, 5); c.lineTo(18, 11)
            }
            c.stroke()
        }
    }
    component OutlinedSurface: Item {
        id: panel
        property color color: window.surface
        property color outlineColor: window.borderColor
        property real outlineWidth: 1
        property real radius: 12
        // Keep fill and outline separate: combined rounded Rectangle borders
        // lose straight edge segments on the Android emulator's GPU path.
        Rectangle {
            anchors.fill: parent
            radius: panel.radius
            color: panel.outlineWidth > 0 ? panel.outlineColor : panel.color
        }
        Rectangle {
            anchors.fill: parent; anchors.margins: panel.outlineWidth
            visible: panel.outlineWidth > 0
            radius: Math.max(0, panel.radius - panel.outlineWidth)
            color: panel.color
        }
    }
    component ActionButton: Button {
        id: action
        property bool primary: false
        property bool quiet: false
        implicitHeight: window.controlHeight
        leftPadding: 16; rightPadding: 16
        font.pixelSize: 16
        Accessible.name: action.text
        Accessible.role: Accessible.Button
        contentItem: Text {
            text: action.text; font: action.font
            color: !action.enabled ? window.muted : action.primary ? "white" : action.quiet ? window.accent : window.ink
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: OutlinedSurface {
            radius: 8
            color: !action.enabled ? window.disabledSurface : action.primary ? (action.down ? window.accentPressed : window.accent) : action.quiet ? "transparent" : window.surface
            outlineWidth: action.quiet || action.primary ? 0 : 1
            outlineColor: action.activeFocus ? window.accent : window.borderColor
        }
    }
    component FormatSelect: ComboBox {
        id: combo
        implicitHeight: window.controlHeight
        wheelEnabled: false
        leftPadding: 12; rightPadding: 30
        font.pixelSize: 16
        Accessible.name: combo.displayText
        Accessible.role: Accessible.ComboBox
        contentItem: Text {
            text: combo.displayText; font: combo.font; color: window.ink
            verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
        }
        background: OutlinedSurface {
            color: window.surface; radius: 8
            outlineColor: combo.activeFocus ? window.accent : window.borderColor
        }
        indicator: Canvas {
            x: combo.width - 24; y: (combo.height - height) / 2
            width: 12; height: 8
            onPaint: {
                const c = getContext("2d"); c.reset()
                c.strokeStyle = window.ink; c.lineWidth = 1.6
                c.beginPath(); c.moveTo(1, 1); c.lineTo(6, 6); c.lineTo(11, 1); c.stroke()
            }
        }
        delegate: ItemDelegate {
            width: combo.width; height: window.controlHeight
            text: modelData
            palette.text: window.ink
            background: Rectangle { color: highlighted ? window.selectedColor : window.surface }
            highlighted: combo.highlightedIndex === index
        }
        popup: Popup {
            y: combo.height + 4; width: combo.width; padding: 4
            implicitHeight: contentItem.implicitHeight + 8
            contentItem: ListView {
                clip: true; implicitHeight: Math.min(contentHeight, window.controlHeight * 5)
                model: combo.popup.visible ? combo.delegateModel : null
                currentIndex: combo.highlightedIndex
                ScrollIndicator.vertical: ScrollIndicator {}
            }
            background: OutlinedSurface { radius: 8 }
        }
    }
    Item {
        id: appHeader
        anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
        height: implicitHeight; z: 2
        objectName: "appHeader"
        readonly property real safeTop: Math.max(SafeArea.margins.top, window.previewSafeTop)
        readonly property real safeLeft: Math.max(SafeArea.margins.left, window.previewSafeLeft)
        readonly property real safeRight: Math.max(SafeArea.margins.right, window.previewSafeRight)
        implicitHeight: window.headerHeight + safeTop
        Item {
            id: headerBody
            objectName: "headerBody"
            x: appHeader.safeLeft; y: appHeader.safeTop
            width: parent.width - appHeader.safeLeft - appHeader.safeRight
            height: window.headerHeight
            Label {
                anchors.left: parent.left; anchors.leftMargin: window.inset
                anchors.verticalCenter: parent.verticalCenter
                text: "视频下载器"; font.pixelSize: 18; font.weight: Font.DemiBold; color: window.ink
            }
        }
    }
    Rectangle {
        id: appFooter
        anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.right: parent.right
        height: visible ? implicitHeight : 0; z: 2
        objectName: "appFooter"
        readonly property real safeBottom: Math.max(SafeArea.margins.bottom, window.previewSafeBottom)
        readonly property real safeLeft: Math.max(SafeArea.margins.left, window.previewSafeLeft)
        readonly property real safeRight: Math.max(SafeArea.margins.right, window.previewSafeRight)
        implicitHeight: window.navigationHeight + safeBottom
        // Navigation does not compete with the input method on short displays.
        visible: !Qt.inputMethod.visible && !window.previewKeyboardVisible
        color: window.surface
        Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: window.borderColor }
        RowLayout {
            id: navigationRow
            objectName: "navigationRow"
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
            anchors.leftMargin: appFooter.safeLeft + 8; anchors.rightMargin: appFooter.safeRight + 8
            height: window.navigationHeight; spacing: 4
            Repeater {
                model: [{label: "下载", icon: "download", page: 0}, {label: "提取 MP3", icon: "audio", page: 1},
                        {label: "作品", icon: "library", page: 3}, {label: "设置", icon: "settings", page: 2}]
                delegate: Button {
                    id: nav
                    required property var modelData
                    required property int index
                    objectName: "navigation" + modelData.page
                    Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredWidth: 1
                    padding: 0
                    Accessible.name: modelData.label
                    checkable: true
                    checked: downloadApp.page === modelData.page
                    onClicked: {
                        linkField.focus = false; Qt.inputMethod.hide(); downloadApp.page = modelData.page
                        if (modelData.page === 3) downloadApp.refreshLibrary()
                    }
                    contentItem: Item {
                        Column {
                            anchors.centerIn: parent
                            spacing: 5
                            LineIcon {
                                anchors.horizontalCenter: parent.horizontalCenter
                                width: window.iconSize; height: window.iconSize
                                kind: nav.modelData.icon; stroke: nav.checked ? window.accent : window.ink
                            }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: nav.modelData.label; font.pixelSize: 12; font.weight: nav.checked ? Font.DemiBold : Font.Normal
                                color: nav.checked ? window.accent : window.muted
                            }
                        }
                    }
                    background: Rectangle {
                        anchors.fill: parent; anchors.margins: 6; radius: 10
                        color: nav.checked ? window.selectedColor : nav.down ? window.disabledSurface : "transparent"
                    }
                }
            }
        }
    }
    ScrollView {
        id: transferScroll
        objectName: "transferScroll"
        visible: downloadApp.page === 0 || downloadApp.page === 1
        anchors.fill: parent
        anchors.topMargin: appHeader.height; anchors.bottomMargin: appFooter.height
        contentWidth: availableWidth
        leftPadding: window.inset + Math.max(SafeArea.margins.left, window.previewSafeLeft); rightPadding: window.inset + Math.max(SafeArea.margins.right, window.previewSafeRight)
        topPadding: window.height < 500 ? 12 : downloadApp.hasTask ? 20 : 44; bottomPadding: 24
        clip: true
        ColumnLayout {
            width: transferScroll.availableWidth
            spacing: window.gap
            Label {
                visible: window.height >= 500
                Layout.fillWidth: true; Layout.bottomMargin: 8
                text: downloadApp.page === 1 ? "提取 MP3" : "你好，今天想保存什么？"
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: window.pageTitleSize; font.weight: Font.Medium; color: window.ink
                wrapMode: Text.Wrap
            }
            OutlinedSurface {
                Layout.fillWidth: true; implicitHeight: window.height < 560 ? 132 : 156
                color: window.surface; radius: 20
                outlineColor: linkField.activeFocus ? window.accent : window.borderColor
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 12; spacing: 4
                    TextArea {
                        id: linkField
                        objectName: "linkField"
                        Layout.fillWidth: true; Layout.fillHeight: true
                        text: downloadApp.link
                        onTextChanged: if (text !== downloadApp.link) downloadApp.link = text
                        placeholderText: "输入链接"
                        color: window.ink; placeholderTextColor: window.muted
                        wrapMode: TextEdit.Wrap; selectByMouse: true
                        padding: 4; font.pixelSize: 16
                        background: Item {}
                        onActiveFocusChanged: if (activeFocus) transferScroll.contentItem.contentY = 0
                        Accessible.name: downloadApp.page === 1 ? "提取 MP3 的作品链接" : "视频链接"
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Item { Layout.fillWidth: true }
                        Button {
                            implicitWidth: 44; implicitHeight: 44
                            Accessible.name: "粘贴链接"
                            enabled: !downloadApp.storageBusy
                            onClicked: downloadApp.paste()
                            contentItem: LineIcon { kind: "paste" }
                            background: Rectangle { color: "transparent"; radius: 22 }
                        }
                        Button {
                            implicitWidth: 44; implicitHeight: 44
                            Accessible.name: downloadApp.page === 1 ? "开始提取 MP3" : "开始下载"
                            enabled: !downloadApp.storageBusy
                            onClicked: { linkField.focus = false; Qt.inputMethod.hide(); downloadApp.start() }
                            contentItem: LineIcon { kind: "arrow"; stroke: "white" }
                            background: Rectangle { color: parent.enabled ? window.accent : window.disabledAccent; radius: 22 }
                        }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                ActionButton {
                    visible: !!downloadApp.platform
                    text: "网页登录"; quiet: true; enabled: !downloadApp.busy && !downloadApp.storageBusy
                    onClicked: downloadApp.login()
                }
                Item { Layout.fillWidth: true }
                ActionButton {
                    objectName: "localVideoButton"
                    visible: downloadApp.page === 1
                    text: "选择本地视频"; quiet: true
                    enabled: !downloadApp.busy && !downloadApp.storageBusy
                    onClicked: { Qt.inputMethod.hide(); downloadApp.chooseLocalVideo() }
                }
            }
            RowLayout {
                visible: downloadApp.queuedCount > 0
                Layout.fillWidth: true
                Label { text: "等待 " + downloadApp.queuedCount; color: window.muted; Layout.fillWidth: true }
                ActionButton { text: "清空等待"; quiet: true; onClicked: downloadApp.clearQueue() }
            }
            Label {
                visible: !!downloadApp.queueStatus; text: downloadApp.queueStatus
                color: window.muted; wrapMode: Text.Wrap; Layout.fillWidth: true
            }
            OutlinedSurface {
                visible: downloadApp.hasTask
                Layout.fillWidth: true
                implicitHeight: taskBody.implicitHeight + 32
                radius: 12
                ColumnLayout {
                    id: taskBody
                    anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                    anchors.margins: 16; spacing: 12
                    Label { text: downloadApp.title; font.pixelSize: 18; font.weight: Font.DemiBold; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    Label { text: downloadApp.status; color: window.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    ProgressBar {
                        id: transferProgress
                        visible: downloadApp.taskBusy || downloadApp.complete
                        Layout.fillWidth: true
                        from: 0; to: 1; value: Math.max(0, downloadApp.progress)
                        indeterminate: downloadApp.taskBusy && downloadApp.progress < 0
                        implicitHeight: 8
                        background: Rectangle { radius: 4; color: window.progressTrack }
                        contentItem: Item {
                            Rectangle {
                                width: transferProgress.indeterminate ? parent.width * 0.35 : parent.width * transferProgress.visualPosition
                                height: parent.height; radius: 4; color: window.accent
                            }
                        }
                    }
                    Label { visible: !!downloadApp.details; text: downloadApp.details; color: window.muted; font.pixelSize: 14; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    RowLayout {
                        visible: downloadApp.complete; Layout.fillWidth: true; spacing: 8
                        ActionButton { text: "查看"; onClicked: downloadApp.openResult(); Layout.fillWidth: true }
                        ActionButton { text: "分享"; onClicked: downloadApp.shareResult(); Layout.fillWidth: true }
                    }
                    ActionButton {
                        visible: downloadApp.page === 0 && downloadApp.complete && downloadApp.canExtractLast
                        text: "导出 MP3"; Layout.fillWidth: true; enabled: !downloadApp.busy && !downloadApp.storageBusy
                        onClicked: downloadApp.extractLastAudio()
                    }
                    ActionButton {
                        visible: downloadApp.taskBusy
                        text: "取消"; Layout.fillWidth: true; onClicked: downloadApp.cancel()
                    }
                }
            }
        }
    }
    ScrollView {
        id: libraryScroll
        objectName: "libraryScroll"
        readonly property var filteredItems: {
            const query = librarySearch.text.trim().toLocaleLowerCase()
            return downloadApp.libraryItems.filter(function(item) {
                return !query || ((item.title || "") + " " + (item.details || "")).toLocaleLowerCase().indexOf(query) >= 0
            })
        }
        readonly property int resultCount: filteredItems.length
        visible: downloadApp.page === 3
        anchors.fill: parent; anchors.topMargin: appHeader.height; anchors.bottomMargin: appFooter.height; contentWidth: availableWidth
        leftPadding: window.inset + Math.max(SafeArea.margins.left, window.previewSafeLeft); rightPadding: window.inset + Math.max(SafeArea.margins.right, window.previewSafeRight); topPadding: 20; bottomPadding: 24
        clip: true
        ColumnLayout {
            width: libraryScroll.availableWidth; spacing: window.gap
            RowLayout {
                Layout.fillWidth: true
                Label { text: "我的作品"; font.pixelSize: window.pageTitleSize; font.weight: Font.DemiBold; Layout.fillWidth: true }
                ActionButton { text: "刷新"; quiet: true; onClicked: downloadApp.refreshLibrary() }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                TextField {
                    id: librarySearch
                    objectName: "librarySearch"
                    Layout.fillWidth: true; implicitHeight: window.controlHeight
                    placeholderText: "搜索作品名称"
                    color: window.ink; placeholderTextColor: window.muted
                    font.pixelSize: 16; leftPadding: 12; rightPadding: 12
                    selectByMouse: true
                    Accessible.name: "搜索作品"
                    background: OutlinedSurface { radius: 8; outlineColor: librarySearch.activeFocus ? window.accent : window.borderColor }
                }
                ActionButton {
                    objectName: "libraryClearSearch"
                    visible: !!librarySearch.text; text: "清除"; quiet: true
                    onClicked: { librarySearch.clear(); librarySearch.focus = false; Qt.inputMethod.hide() }
                }
            }
            Label {
                visible: !!downloadApp.libraryStatus
                text: downloadApp.libraryStatus; color: window.muted; Layout.fillWidth: true; wrapMode: Text.Wrap
            }
            Label {
                objectName: "libraryEmptyState"
                visible: libraryScroll.resultCount === 0
                text: librarySearch.text.trim() ? "没有找到匹配作品" : "还没有保存的作品"
                color: window.muted; Layout.fillWidth: true
                Layout.topMargin: 36; horizontalAlignment: Text.AlignHCenter
            }
            Repeater {
                model: libraryScroll.filteredItems
                delegate: OutlinedSurface {
                    id: libraryCard
                    required property var modelData
                    Layout.fillWidth: true; implicitHeight: libraryBody.implicitHeight + 32
                    radius: 12
                    ColumnLayout {
                        id: libraryBody
                        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                        anchors.margins: 16; spacing: 12
                        Label { text: libraryCard.modelData.title || "作品"; font.pixelSize: 16; font.weight: Font.DemiBold; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { visible: !!libraryCard.modelData.details; text: libraryCard.modelData.details || ""; color: window.muted; font.pixelSize: 14; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        ActionButton {
                            visible: libraryCard.modelData.kind === "video"
                            text: "导出 MP3"; quiet: true; Layout.alignment: Qt.AlignRight
                            enabled: !downloadApp.busy && !downloadApp.storageBusy
                            onClicked: downloadApp.extractLibraryAudio(libraryCard.modelData.id)
                        }
                        RowLayout {
                            Layout.fillWidth: true; spacing: 8
                            ActionButton { text: "查看"; Layout.fillWidth: true; onClicked: downloadApp.openLibraryItem(libraryCard.modelData.id) }
                            ActionButton { text: "分享"; Layout.fillWidth: true; onClicked: downloadApp.shareLibraryItem(libraryCard.modelData.id) }
                            Button {
                                implicitWidth: 44; implicitHeight: 48; padding: 10
                                Accessible.name: "删除作品"
                                onClicked: { removeDialog.itemId = libraryCard.modelData.id; removeDialog.open() }
                                contentItem: LineIcon { kind: "trash" }
                                background: Rectangle { color: parent.down ? window.disabledSurface : "transparent"; radius: 8 }
                            }
                        }
                    }
                }
            }
        }
    }
    Dialog {
        id: removeDialog
        objectName: "removeDialog"
        property string itemId: ""
        title: "删除作品？"
        modal: true; anchors.centerIn: Overlay.overlay
        width: Math.min(window.width - 32, 320)
        padding: 20; spacing: 0
        standardButtons: Dialog.NoButton
        background: OutlinedSurface { radius: 16 }
        header: Label {
            text: removeDialog.title; color: window.ink
            leftPadding: 20; rightPadding: 20; topPadding: 20
            font.pixelSize: 20; font.weight: Font.DemiBold
            wrapMode: Text.Wrap
        }
        contentItem: Label {
            text: "将删除这个作品的本地文件。"; color: window.ink
            font.pixelSize: 16; wrapMode: Text.Wrap
        }
        footer: Item {
            implicitHeight: window.controlHeight + 20
            RowLayout {
                anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                anchors.leftMargin: 20; anchors.rightMargin: 20; anchors.bottomMargin: 20
                spacing: 12
                ActionButton {
                    objectName: "removeCancelButton"
                    text: "取消"; Layout.fillWidth: true; Layout.preferredWidth: 1
                    onClicked: removeDialog.reject()
                }
                ActionButton {
                    objectName: "removeConfirmButton"
                    text: "删除"; primary: true; Layout.fillWidth: true; Layout.preferredWidth: 1
                    onClicked: removeDialog.accept()
                }
            }
        }
        onAccepted: downloadApp.removeLibraryItem(itemId)
    }
    ScrollView {
        id: settingsScroll
        objectName: "settingsScroll"
        visible: downloadApp.page === 2
        anchors.fill: parent; anchors.topMargin: appHeader.height; anchors.bottomMargin: appFooter.height; contentWidth: availableWidth
        leftPadding: window.inset + Math.max(SafeArea.margins.left, window.previewSafeLeft); rightPadding: window.inset + Math.max(SafeArea.margins.right, window.previewSafeRight); topPadding: 24; bottomPadding: 32
        clip: true
        ColumnLayout {
            width: settingsScroll.availableWidth; spacing: 24
            Label { text: "设置"; font.pixelSize: window.pageTitleSize; font.weight: Font.DemiBold }
            OutlinedSurface {
                Layout.fillWidth: true; implicitHeight: formatBody.implicitHeight + 32
                radius: 12
                ColumnLayout {
                    id: formatBody
                    anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                    anchors.margins: 16; spacing: 16
                    Label { text: "导出格式"; font.pixelSize: 18; font.weight: Font.DemiBold }
                    RowLayout {
                        Layout.fillWidth: true; spacing: 8
                        Label { text: "视频"; Layout.preferredWidth: 64 }
                        FormatSelect {
                            Layout.fillWidth: true; model: ["MP4（默认）", "MKV", "MOV", "WebM"]
                            currentIndex: ["mp4", "mkv", "mov", "webm"].indexOf(downloadApp.videoFormat)
                            onActivated: downloadApp.videoFormat = ["mp4", "mkv", "mov", "webm"][currentIndex]
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true; spacing: 8
                        Label { text: "图片"; Layout.preferredWidth: 64 }
                        FormatSelect {
                            Layout.fillWidth: true; model: ["PNG（默认）", "JPEG", "WebP"]
                            currentIndex: ["png", "jpg", "webp"].indexOf(downloadApp.imageFormat)
                            onActivated: downloadApp.imageFormat = ["png", "jpg", "webp"][currentIndex]
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true; spacing: 8
                        Label { text: "MP3"; Layout.preferredWidth: 64 }
                        FormatSelect {
                            Layout.fillWidth: true; model: ["128 kbps", "192 kbps", "256 kbps", "320 kbps"]
                            currentIndex: [128, 192, 256, 320].indexOf(downloadApp.audioBitrate)
                            onActivated: downloadApp.audioBitrate = [128, 192, 256, 320][currentIndex]
                        }
                    }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true; spacing: 12
                Label { text: "软件更新"; font.pixelSize: 18; font.weight: Font.DemiBold }
                CheckBox {
                    text: "启动时检查更新"; checked: downloadApp.autoUpdate
                    onToggled: downloadApp.autoUpdate = checked
                    palette.windowText: window.ink
                }
                ActionButton {
                    Layout.fillWidth: true
                    text: downloadApp.updateAvailable ? "下载更新" : "检查更新"
                    onClicked: downloadApp.updateAvailable ? downloadApp.openUpdate() : downloadApp.checkForUpdates(true)
                }
                Label { visible: !!downloadApp.updateStatus; text: downloadApp.updateStatus; color: window.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                Label { text: "当前版本 " + downloadApp.version; color: window.muted; font.pixelSize: 14 }
            }
            ColumnLayout {
                Layout.fillWidth: true; spacing: 8
                Label { text: "保存位置"; font.pixelSize: 18; font.weight: Font.DemiBold }
                Label { text: downloadApp.saveLocation; color: window.muted; font.pixelSize: 14; wrapMode: Text.Wrap; Layout.fillWidth: true }
                Label { visible: !!downloadApp.libraryStatus; text: downloadApp.libraryStatus; color: window.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                RowLayout {
                    Layout.fillWidth: true; spacing: 8
                    ActionButton { text: "更改位置"; Layout.fillWidth: true; enabled: !downloadApp.busy && !downloadApp.storageBusy; onClicked: downloadApp.chooseSaveLocation() }
                    ActionButton { text: "默认位置"; quiet: true; enabled: !downloadApp.busy && !downloadApp.storageBusy; onClicked: downloadApp.resetSaveLocation() }
                }
                ActionButton {
                    visible: downloadApp.storageBusy
                    text: "重试清理"; quiet: true
                    onClicked: downloadApp.refreshLibrary()
                }
            }
            DisclosureGroup {
                title: "运行日志"
            }
        }
    }
    component DisclosureGroup: ColumnLayout {
        property string title
        Layout.fillWidth: true; spacing: 8
        CheckBox { id: logsToggle; text: parent.title; palette.windowText: window.muted }
        TextArea {
            visible: logsToggle.checked
            Layout.fillWidth: true; Layout.preferredHeight: 180
            text: downloadApp.logs; readOnly: true; wrapMode: TextEdit.Wrap
            color: window.muted; font.pixelSize: 13
            background: OutlinedSurface { radius: 8 }
        }
    }
}

