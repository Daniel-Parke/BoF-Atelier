pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: table
    required property var dataTable
    required property bool tv
    required property color accent
    readonly property var headings: dataTable.columns || []
    readonly property bool stack: width < headings.length * (tv ? 185 : 140)
    spacing: 0
    Text {
        Layout.fillWidth: true; Layout.bottomMargin: 6
        visible: !!text; text: table.dataTable.title || ""; font.family: "Segoe UI"
        font.pixelSize: table.tv ? 24 : 20; font.weight: Font.DemiBold; color: "#283732"
        wrapMode: Text.WordWrap; textFormat: Text.PlainText; Accessible.role: Accessible.Heading
    }
    Rectangle {
        Layout.fillWidth: true; implicitHeight: 2; color: table.accent
    }
    RowLayout {
        visible: !table.stack; Layout.fillWidth: true; Layout.topMargin: 5; Layout.bottomMargin: 5
        spacing: 14
        Repeater {
            model: table.headings
            delegate: Text {
                required property string modelData
                Layout.fillWidth: true; Layout.preferredWidth: 1; color: table.accent
                text: modelData; font.pixelSize: table.tv ? 19 : 15; font.weight: Font.DemiBold; font.family: "Segoe UI"
                textFormat: Text.PlainText; wrapMode: Text.WordWrap
            }
        }
    }
    Repeater {
        model: table.dataTable.rows || []
        delegate: ColumnLayout {
            id: record
            required property var modelData
            Layout.fillWidth: true; spacing: 0
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#cabfa9" }
            GridLayout {
                Layout.fillWidth: true; Layout.topMargin: 8; Layout.bottomMargin: 8
                columns: table.stack ? 1 : table.headings.length; columnSpacing: 14; rowSpacing: 2
                Repeater {
                    model: record.modelData
                    delegate: Text {
                        required property int index
                        required property var modelData
                        Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop
                        text: table.stack && index > 0 ? table.headings[index] + " · " + modelData : modelData
                        Accessible.name: table.headings[index] + ", " + modelData
                        font.family: "Segoe UI"; font.pixelSize: table.tv ? 22 : 17
                        font.weight: index ? Font.Normal : Font.DemiBold
                        color: "#283732"; textFormat: Text.PlainText; wrapMode: Text.WordWrap; lineHeight: 1.13
                    }
                }
            }
        }
    }
}
