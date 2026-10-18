import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    visible: true
    width: 420; height: 880
    title: "视频下载器"
    color: "#f5f6fa"
    readonly property color ink: "#202533"
    readonly property color muted: "#697386"
    readonly property color accent: "#dc4775"
    readonly property int bodySize: 18
    readonly property int gap: 18
    font.pixelSize: bodySize
    palette.text: ink
    palette.windowText: ink

    component ActionButton: Button {
        id: action
        property bool primary: false
        implicitHeight: 54
        leftPadding: 18; rightPadding: 18
        font.pixelSize: window.bodySize
        font.bold: primary
        contentItem: Text {
            text: action.text
            color: !action.enabled ? "#a1a7b4" : action.primary ? "white" : window.ink
            font: action.font
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 10
            color: !action.enabled ? "#eff0f4" : action.primary ? (action.down ? "#c83765" : window.accent) : "white"
            border.width: action.primary ? 0 : 1; border.color: "#e2e5ed"
        }
    }
    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth
        leftPadding: 22; rightPadding: 22; topPadding: 24; bottomPadding: 28
        clip: true
        ColumnLayout {
            width: parent.width
            spacing: window.gap
            Label { text: "视频下载器"; font.pixelSize: 30; font.bold: true }
            Label { text: "视频链接"; font.bold: true }
            TextArea {
                id: linkField
                Layout.fillWidth: true
                implicitHeight: 130
                placeholderText: "链接粘贴处"
                text: downloadApp.link
                onTextChanged: if (text !== downloadApp.link) downloadApp.link = text
                enabled: !downloadApp.busy
                wrapMode: TextEdit.Wrap
                selectByMouse: true
                padding: 16
                background: Rectangle { color: "white"; radius: 12; border.color: linkField.activeFocus ? window.accent : "#e2e5ed" }
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { text: "粘贴"; enabled: !downloadApp.busy; onClicked: downloadApp.paste() }
            }
            ActionButton {
                Layout.fillWidth: true
                primary: true
                text: downloadApp.busy ? "下载进行中…" : downloadApp.complete ? "再下载一个" : "开始下载"
                enabled: !downloadApp.busy
                onClicked: { linkField.focus = false; Qt.inputMethod.hide(); downloadApp.start() }
            }
            RowLayout {
                Layout.fillWidth: true
                Label {
                    text: "需要账号权限时，先在软件内登录。"
                    color: window.muted; font.pixelSize: 15; Layout.fillWidth: true; wrapMode: Text.Wrap
                }
                ActionButton { text: "网页登录"; enabled: !downloadApp.busy && !!downloadApp.platform; onClicked: downloadApp.login() }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: "#e2e5ed" }
            Label { text: downloadApp.title; font.pixelSize: 22; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { text: downloadApp.status; wrapMode: Text.Wrap; Layout.fillWidth: true }
            ProgressBar {
                id: transferProgress
                Layout.fillWidth: true
                from: 0; to: 1; value: Math.max(0, downloadApp.progress)
                indeterminate: downloadApp.busy && downloadApp.progress < 0
                implicitHeight: 10
                background: Rectangle { radius: 5; color: "#e4e7ee" }
                contentItem: Item {
                    Rectangle {
                        id: progressFill
                        width: transferProgress.indeterminate ? parent.width * 0.35 : parent.width * transferProgress.visualPosition
                        height: parent.height; radius: 5; color: window.accent
                        SequentialAnimation on opacity {
                            running: transferProgress.indeterminate
                            loops: Animation.Infinite
                            onStopped: progressFill.opacity = 1
                            NumberAnimation { from: 0.35; to: 1; duration: 650 }
                            NumberAnimation { from: 1; to: 0.35; duration: 650 }
                        }
                    }
                }
            }
            Label { text: downloadApp.details; color: window.muted; font.pixelSize: 16; wrapMode: Text.Wrap; Layout.fillWidth: true }
            RowLayout {
                Layout.fillWidth: true
                ActionButton { text: "查看结果"; enabled: downloadApp.complete; onClicked: downloadApp.openResult(); Layout.fillWidth: true }
                ActionButton { text: "分享文件"; enabled: downloadApp.complete; onClicked: downloadApp.shareResult(); Layout.fillWidth: true }
            }
            ActionButton { visible: downloadApp.busy; text: "取消下载"; onClicked: downloadApp.cancel(); Layout.fillWidth: true }
            RowLayout {
                Layout.fillWidth: true
                CheckBox { id: detailsToggle; text: "更多选项"; font.pixelSize: 15; palette.windowText: window.muted }
                Item { Layout.fillWidth: true }
                ActionButton {
                    text: downloadApp.updateAvailable ? "下载更新" : "检查更新"
                    font.pixelSize: 15
                    onClicked: downloadApp.updateAvailable ? downloadApp.openUpdate() : downloadApp.checkForUpdates(true)
                }
            }
            Label { visible: !!downloadApp.updateStatus; text: downloadApp.updateStatus; color: window.muted; font.pixelSize: 15; wrapMode: Text.Wrap; Layout.fillWidth: true }
            CheckBox {
                visible: detailsToggle.checked
                text: "启动时检查更新"; font.pixelSize: 15
                checked: downloadApp.autoUpdate
                onToggled: downloadApp.autoUpdate = checked
            }
            Label { visible: detailsToggle.checked; text: "当前版本 " + downloadApp.version; color: window.muted; font.pixelSize: 14 }
            TextArea {
                visible: detailsToggle.checked
                Layout.fillWidth: true; Layout.preferredHeight: 200
                text: downloadApp.logs; readOnly: true; wrapMode: TextEdit.Wrap
                font.pixelSize: 13; color: window.muted; selectByMouse: true
            }
            Label { text: "保存位置：下载 / 视频下载器"; color: window.muted; font.pixelSize: 14; wrapMode: Text.Wrap; Layout.fillWidth: true }
        }
    }
}
