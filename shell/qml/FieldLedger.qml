pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: ledger
    required property var records
    required property bool monsters
    required property color accent
    property bool tv: false
    readonly property bool compact: width < (tv ? 470 : 295)
    signal entryRequested(var row, string returnKey)
    spacing: 0
    Rectangle { Layout.fillWidth: true; implicitHeight: 2; color: ledger.accent }
    GridLayout {
        Layout.fillWidth: true; visible: !ledger.compact
        Layout.topMargin: 5; Layout.bottomMargin: 6; columns: 2; columnSpacing: 12
        Label {
            Layout.fillWidth: true; Layout.preferredWidth: 39
            text: ledger.monsters ? "Enemy" : "Item"; color: ledger.accent
            font.family: "Segoe UI"; font.weight: Font.DemiBold; font.pixelSize: ledger.tv ? 18 : 14
        }
        Label {
            Layout.fillWidth: true; Layout.preferredWidth: 61
            text: ledger.monsters ? "In battle" : "Where to look"; color: ledger.accent
            font.family: "Segoe UI"; font.weight: Font.DemiBold; font.pixelSize: ledger.tv ? 18 : 14
        }
    }
    Repeater {
        model: ledger.records
        delegate: Button {
            id: record
            required property var modelData
            required property int index
            readonly property bool guideAction: true
            objectName: (ledger.monsters ? "enemy." : "item.") + modelData.name.toLowerCase()
            readonly property string returnKey: JSON.stringify([objectName, modelData.where, index])
            Layout.fillWidth: true; Layout.minimumWidth: 0
            implicitHeight: cells.implicitHeight + 17
            leftPadding: 4; rightPadding: 4; topPadding: 8; bottomPadding: 9
            focusPolicy: Qt.StrongFocus; hoverEnabled: true
            Accessible.name: modelData.name; Accessible.description: [modelData.where,modelData.detail].filter(Boolean).join(". ")
            function activate() { clicked() }
            onClicked: {
                forceActiveFocus()
                ledger.entryRequested(modelData, returnKey)
            }
            Keys.onReturnPressed: event => { if (!event.isAutoRepeat) activate(); event.accepted=true }
            Keys.onEnterPressed: event => { if (!event.isAutoRepeat) activate(); event.accepted=true }
            background: Rectangle {
                color: record.hovered || record.down ? "#e8e4d5" : "transparent"
                border.width: record.activeFocus ? 2 : 0; border.color: "#006383"
                Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: "#c7bda7" }
            }
            contentItem: GridLayout {
                id: cells
                columns: ledger.compact ? 1 : 2; columnSpacing: 12; rowSpacing: 4
                ColumnLayout {
                    Layout.fillWidth: true; Layout.preferredWidth: 39; Layout.minimumWidth: 0
                    Layout.alignment: Qt.AlignTop; spacing: 3
                    Text {
                        Layout.fillWidth: true; text: record.modelData.name
                        font.family: "Segoe UI"; font.pixelSize: ledger.tv ? 21 : 16; font.weight: Font.DemiBold
                        font.underline: true; color: ledger.accent; wrapMode: Text.WordWrap; textFormat: Text.PlainText
                    }
                    Text {
                        Layout.fillWidth: true; text: record.modelData.where || ""; visible: !!text
                        font.family: "Segoe UI"; font.pixelSize: ledger.tv ? 18 : 14
                        color: "#52584f"; wrapMode: Text.WordWrap; textFormat: Text.PlainText; lineHeight: 1.12
                    }
                }
                Text {
                    Layout.fillWidth: true; Layout.preferredWidth: 61; Layout.minimumWidth: 0; Layout.alignment: Qt.AlignTop
                    text: record.modelData.detail; font.family: "Segoe UI"
                    font.pixelSize: ledger.tv ? 21 : 16; color: "#283630"; wrapMode: Text.WordWrap
                    textFormat: Text.PlainText; lineHeight: 1.16
                }
            }
        }
    }
}
