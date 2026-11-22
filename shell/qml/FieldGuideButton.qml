import QtQuick
import QtQuick.Controls.Basic

Button {
    id: control
    property color accent: "#285647"
    property color paper: "#fffdf5"
    property string detail: ""
    property string art: ""
    property bool largePlate: false
    property bool selected: false
    property bool primary: false
    property bool quiet: false
    property bool dark: false
    property bool tv: false
    readonly property bool guideAction: true
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    leftPadding: art && !largePlate ? 6 : quiet ? 10 : 13
    rightPadding: quiet ? 10 : 13
    topPadding: 8
    bottomPadding: 8
    implicitWidth: Math.max(96, (art && !largePlate ? thumbnail.width + 12 : 0) + Math.max(caption.implicitWidth, note.implicitWidth) + leftPadding + rightPadding)
    implicitHeight: Math.max(tv ? 55 : 43, visual.implicitHeight + topPadding + bottomPadding)
    Accessible.name: text
    Accessible.description: detail
    function activate() { clicked() }
    Keys.onReturnPressed: event => {
        if (enabled && !event.isAutoRepeat) activate()
        event.accepted = true
    }
    Keys.onEnterPressed: event => {
        if (enabled && !event.isAutoRepeat) activate()
        event.accepted = true
    }
    background: Rectangle {
        radius: 2
        color: control.dark ? (control.hovered || control.selected ? "#43514b" : "transparent")
              : control.primary ? control.accent : control.selected ? Qt.tint(control.paper, Qt.rgba(control.accent.r, control.accent.g, control.accent.b, 0.10))
              : control.hovered || control.down ? Qt.tint(control.paper, Qt.rgba(control.accent.r, control.accent.g, control.accent.b, 0.08))
              : control.quiet ? "transparent" : control.paper
        border.width: control.activeFocus || control.selected ? 2 : control.quiet ? 0 : 1
        border.color: control.activeFocus ? (control.dark ? "#f6d08e" : "#006383") : control.selected ? (control.largePlate ? "#e0ab4e" : control.dark ? "#a6aa8a" : control.accent) : "#bcb7a4"
        Rectangle {
            visible: control.activeFocus && control.primary
            anchors.fill: parent
            anchors.margins: 3
            border.width: 1
            border.color: "#fff9e8"
            color: "transparent"
            radius: 2
        }
    }
    contentItem: Item {
        id: visual
        implicitHeight: control.largePlate ? thumbnail.height + words.implicitHeight + 7
                      : Math.max(thumbnail.visible ? thumbnail.height : 0, words.implicitHeight)
        Image {
            id: thumbnail
            visible: !!control.art
            anchors.left: control.largePlate ? undefined : parent.left
            anchors.horizontalCenter: control.largePlate ? parent.horizontalCenter : undefined
            anchors.verticalCenter: control.largePlate ? undefined : parent.verticalCenter
            anchors.top: control.largePlate ? parent.top : undefined
            width: control.largePlate ? parent.width : control.tv ? 80 : 62
            height: control.largePlate ? Math.min(control.tv ? 175 : 135, width*.76) : control.tv ? 66 : 53
            source: control.art
            fillMode: control.largePlate ? Image.PreserveAspectFit : Image.PreserveAspectCrop
        }
        Column {
            id: words
            anchors.left: thumbnail.visible && !control.largePlate ? thumbnail.right : parent.left
            anchors.leftMargin: thumbnail.visible && !control.largePlate ? 10 : 0
            anchors.right: parent.right
            anchors.verticalCenter: control.largePlate ? undefined : parent.verticalCenter
            anchors.top: control.largePlate ? thumbnail.bottom : undefined
            anchors.topMargin: control.largePlate ? 7 : 0
            spacing: 3
            Text {
                id: caption
                width: parent.width
                text: control.text
                textFormat: Text.PlainText
                color: control.dark || control.primary ? "#fff8e5" : control.accent
                font.family: control.largePlate ? "Gloock" : "Segoe UI"
                font.weight: Font.DemiBold
                font.pixelSize: control.largePlate ? (control.tv ? 28 : 23) : control.tv ? 22 : 16
                lineHeight: 1.1
                wrapMode: Text.WordWrap
            }
            Text {
                id: note
                visible: !!text
                width: parent.width
                text: control.detail
                textFormat: Text.PlainText
                color: control.dark || control.primary ? "#f7f4ea" : "#4b554e"
                font.family: "Segoe UI"
                font.pixelSize: control.tv ? 20 : 15
                lineHeight: 1.16
                wrapMode: Text.WordWrap
            }
        }
        Rectangle {
            visible: control.selected && !!control.art; z: 2
            anchors.top: parent.top; anchors.right: parent.right
            width: control.tv ? 27 : 22; height: width; radius: width/2
            color: "#285647"
            Text { anchors.centerIn: parent; text: "✓"; color: "#fff8e5"; font.pixelSize: control.tv ? 20 : 16; font.bold: true }
            Accessible.ignored: true
        }
    }
}
