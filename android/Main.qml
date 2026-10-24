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
    readonly property int inset: 24
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
                c.ellipse(4, 4, 16, 16); c.ellipse(9, 9, 6, 6)
                c.moveTo(12, 1); c.lineTo(12, 4); c.moveTo(12, 20); c.lineTo(12, 23)
                c.moveTo(1, 12); c.lineTo(4, 12); c.moveTo(20, 12); c.lineTo(23, 12)
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
    component ActionButton: Button {
        id: action
        property bool primary: false
        property bool quiet: false
        implicitHeight: window.controlHeight
        leftPadding: 16; rightPadding: 16
        font.pixelSize: 16
        contentItem: Text {
            text: action.text; font: action.font
            color: !action.enabled ? window.muted : action.primary ? "white" : action.quiet ? window.accent : window.ink
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 8
            color: !action.enabled ? window.disabledSurface : action.primary ? (action.down ? window.accentPressed : window.accent) : action.quiet ? "transparent" : window.surface
            border.width: action.quiet || action.primary ? 0 : 1
            border.color: action.activeFocus ? window.accent : window.borderColor
        }
    }
    component FormatSelect: ComboBox {
        id: combo
        implicitHeight: window.controlHeight
        wheelEnabled: false
        leftPadding: 12; rightPadding: 30
        font.pixelSize: 16
        contentItem: Text {
            text: combo.displayText; font: combo.font; color: window.ink
            verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
        }
        background: Rectangle {
            color: window.surface; radius: 8
            border.color: combo.activeFocus ? window.accent : window.borderColor
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
            background: Rectangle { color: window.surface; radius: 8; border.color: window.borderColor }
        }
    }
    header: Item {
        implicitHeight: 60
        Label {
            anchors.left: parent.left; anchors.leftMargin: window.inset
            anchors.verticalCenter: parent.verticalCenter
            text: "视频下载器"; font.pixelSize: 18; font.weight: Font.DemiBold; color: window.ink
        }
    }
    footer: Rectangle {
        implicitHeight: 76 + SafeArea.margins.bottom
        color: window.surface
        Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: window.borderColor }
        RowLayout {
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
            anchors.leftMargin: 12; anchors.rightMargin: 12; height: 76
            spacing: 8
            Repeater {
                model: [{label: "下载", icon: "download"}, {label: "提取 MP3", icon: "audio"}, {label: "设置", icon: "settings"}]
                delegate: Button {
                    id: nav
                    required property var modelData
                    required property int index
                    Layout.fillWidth: true; Layout.fillHeight: true
                    Accessible.name: modelData.label
                    onClicked: { linkField.focus = false; Qt.inputMethod.hide(); downloadApp.page = index }
                    contentItem: Column {
                        spacing: 4
                        LineIcon { anchors.horizontalCenter: parent.horizontalCenter; kind: nav.modelData.icon; stroke: downloadApp.page === nav.index ? window.accent : window.ink }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: nav.modelData.label; font.pixelSize: 12
                            color: downloadApp.page === nav.index ? window.accent : window.muted
                        }
                    }
                    background: Rectangle {
                        anchors.fill: parent; anchors.margins: 8; radius: 10
                        color: downloadApp.page === nav.index ? window.selectedColor : "transparent"
                    }
                }
            }
        }
    }
    ScrollView {
        id: transferScroll
        visible: downloadApp.page !== 2
        anchors.fill: parent
        contentWidth: availableWidth
        leftPadding: window.inset; rightPadding: window.inset
        topPadding: downloadApp.hasTask ? 24 : 84; bottomPadding: 32
        clip: true
        ColumnLayout {
            width: transferScroll.availableWidth
            spacing: window.gap
            Label {
                Layout.fillWidth: true; Layout.bottomMargin: 8
                text: downloadApp.page === 1 ? "提取 MP3" : "你好，今天想保存什么？"
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: 24; font.weight: Font.Medium; color: window.ink
                wrapMode: Text.Wrap
            }
            Rectangle {
                Layout.fillWidth: true; implicitHeight: 160
                color: window.surface; radius: 20
                border.color: linkField.activeFocus ? window.accent : window.borderColor
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
                        Accessible.name: downloadApp.page === 1 ? "提取 MP3 的作品链接" : "视频链接"
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Item { Layout.fillWidth: true }
                        Button {
                            implicitWidth: 44; implicitHeight: 44
                            Accessible.name: "粘贴链接"
                            enabled: !downloadApp.taskBusy
                            onClicked: downloadApp.paste()
                            contentItem: LineIcon { kind: "paste" }
                            background: Rectangle { color: "transparent"; radius: 22 }
                        }
                        Button {
                            implicitWidth: 44; implicitHeight: 44
                            Accessible.name: downloadApp.page === 1 ? "开始提取 MP3" : "开始下载"
                            enabled: !downloadApp.busy
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
                    text: "网页登录"; quiet: true; enabled: !downloadApp.busy
                    onClicked: downloadApp.login()
                }
                Item { Layout.fillWidth: true }
                ActionButton {
                    objectName: "localVideoButton"
                    visible: downloadApp.page === 1
                    text: "选择本地视频"; quiet: true
                    enabled: !downloadApp.busy
                    onClicked: { Qt.inputMethod.hide(); downloadApp.chooseLocalVideo() }
                }
            }
            Rectangle {
                visible: downloadApp.hasTask
                Layout.fillWidth: true
                implicitHeight: taskBody.implicitHeight + 32
                color: window.surface; radius: 12; border.color: window.borderColor
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
                        text: "导出 MP3"; Layout.fillWidth: true; enabled: !downloadApp.busy
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
        id: settingsScroll
        visible: downloadApp.page === 2
        anchors.fill: parent; contentWidth: availableWidth
        leftPadding: window.inset; rightPadding: window.inset; topPadding: 24; bottomPadding: 32
        clip: true
        ColumnLayout {
            width: settingsScroll.availableWidth; spacing: 24
            Label { text: "设置"; font.pixelSize: 24; font.weight: Font.DemiBold }
            Rectangle {
                Layout.fillWidth: true; implicitHeight: formatBody.implicitHeight + 32
                color: window.surface; radius: 12; border.color: window.borderColor
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
                Label { text: "下载 / 视频下载器"; color: window.muted; font.pixelSize: 14; wrapMode: Text.Wrap; Layout.fillWidth: true }
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
            background: Rectangle { color: window.surface; radius: 8; border.color: window.borderColor }
        }
    }
}

