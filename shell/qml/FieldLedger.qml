pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: ledger
    required property var records
    required property bool monsters
    required property color accent
    property bool tv: false
    property bool compact: width < (tv ? 570 : 405)
    spacing: 0
    Rectangle {
        Layout.fillWidth: true; color: ledger.accent; implicitHeight: ledger.tv ? 35 : 29
        Text {
            anchors.left: parent.left; anchors.leftMargin: 12; anchors.verticalCenter: parent.verticalCenter
            text: ledger.monsters ? "ENCOUNTER  /  FIELD NOTES" : "ITEM  /  WHERE TO LOOK"
            color: "#fffaf0"; font.family: "Segoe UI"; font.weight: Font.DemiBold
            font.letterSpacing: 1; font.pixelSize: ledger.tv ? 15 : 11
        }
    }
    Repeater {
        model: ledger.records
        delegate: Rectangle {
            id: record
            required property var modelData
            required property int index
            Layout.fillWidth: true; implicitHeight: line.implicitHeight + 20
            color: index % 2 ? "#f5f1e8" : "#fffcf3"
            GridLayout {
                id: line
                anchors.left: parent.left; anchors.right: parent.right; anchors.margins: 12
                anchors.verticalCenter: parent.verticalCenter
                columns: ledger.compact ? 1 : 2; columnSpacing: 13; rowSpacing: 4
                ColumnLayout {
                    Layout.fillWidth: true; Layout.preferredWidth: Math.max(100,record.width*.35)
                    Layout.alignment: Qt.AlignTop; spacing: 3
                    Text {
                        Layout.fillWidth: true; text: record.modelData.name
                        font.family: "Georgia"; font.pixelSize: ledger.tv ? 24 : 19
                        color: ledger.accent; wrapMode: Text.WordWrap
                    }
                    Text {
                        Layout.fillWidth: true; text: record.modelData.where
                        font.family: "Segoe UI"; font.pixelSize: ledger.tv ? 17 : 13
                        color: "#555d51"; wrapMode: Text.WordWrap
                    }
                }
                Text {
                    Layout.fillWidth: true; Layout.preferredWidth: Math.max(125,record.width*.62)
                    text: record.modelData.detail; font.family: "Segoe UI"
                    font.pixelSize: ledger.tv ? 21 : 16; color: "#28362e"; wrapMode: Text.WordWrap
                }
            }
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: "#d6d1c4" }
        }
    }
}
