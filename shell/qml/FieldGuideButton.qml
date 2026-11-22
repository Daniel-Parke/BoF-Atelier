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
    property bool tv: false
    readonly property bool guideAction: true
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    leftPadding: art && !largePlate ? 5 : 14
    rightPadding: 14
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
        radius: 3
        color: control.primary ? control.accent : control.selected ? Qt.tint(control.paper, Qt.rgba(control.accent.r, control.accent.g, control.accent.b, 0.14))
              : control.hovered || control.down ? Qt.tint(control.paper, Qt.rgba(control.accent.r, control.accent.g, control.accent.b, 0.08))
              : control.quiet ? "transparent" : control.paper
        border.width: control.activeFocus || control.selected ? 2 : control.quiet ? 0 : 1
        border.color: control.activeFocus ? "#ab521d" : control.selected ? control.accent : "#c6c3b2"
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
            height: control.largePlate ? Math.min(control.tv ? 135 : 111, width*0.8) : control.tv ? 66 : 53
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
                color: control.primary ? "#fffef6" : control.accent
                font.family: "Segoe UI"
                font.weight: Font.DemiBold
                font.pixelSize: control.tv ? 21 : 15
                wrapMode: Text.WordWrap
            }
            Text {
                id: note
                visible: !!text
                width: parent.width
                text: control.detail
                textFormat: Text.PlainText
                color: control.primary ? "#f7f4ea" : "#4d584f"
                font.family: "Segoe UI"
                font.pixelSize: control.tv ? 18 : 13
                wrapMode: Text.WordWrap
            }
        }
    }
}
