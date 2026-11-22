pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: landmarks
    required property var chart
    required property color accent
    property bool tv: false
    property int chosen: 0
    readonly property var points: chart?.points || []
    onChartChanged: chosen = 0
    spacing: 0

    Repeater {
        model: landmarks.points
        delegate: ColumnLayout {
            id: stop
            required property int index
            required property var modelData
            Layout.fillWidth: true; spacing: 0
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#c6baa0" }
            FieldGuideButton {
                Layout.fillWidth: true; tv: landmarks.tv; accent: landmarks.accent
                objectName: "atlasKey" + stop.index
                quiet: true; selected: stop.index === landmarks.chosen
                Accessible.checkable: true; Accessible.checked: selected
                text: (stop.index+1) + ".  " + stop.modelData.name
                detail: selected ? stop.modelData.note : ""
                onClicked: landmarks.chosen = stop.index
            }
        }
    }
}
