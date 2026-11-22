pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: atlas
    required property var chart
    required property color accent
    property bool tv: false
    property int chosen: 0
    onChartChanged: chosen = 0
    spacing: 0
    readonly property var points: chart ? chart.points : []
    readonly property var selected: points[chosen] || ({name:"",note:""})
    Rectangle {
        Layout.fillWidth: true
        implicitHeight: atlas.tv ? 211 : 171
        color: "#273a37"
        clip: true
        Text {
            x: 15; y: 9
            text: "LANDMARK MAP   /   SCHEMATIC"
            color: "#e4d9b9"; font.family: "Segoe UI"; font.pixelSize: atlas.tv ? 15 : 11
            font.weight: Font.DemiBold; font.letterSpacing: 1
        }
        Item {
            id: plot
            anchors.fill: parent; anchors.margins: 10; anchors.topMargin: 30; anchors.bottomMargin: 8
            Canvas {
                id: drawing
                anchors.fill: parent
                property var diagram: atlas.chart
                onDiagramChanged: requestPaint()
                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()
                onPaint: {
                    const pen = getContext("2d")
                    pen.clearRect(0, 0, width, height)
                    if (!diagram) return
                    pen.strokeStyle = "#455550"; pen.lineWidth = 0.8
                    pen.beginPath()
                    for (let x = 0; x < width; x += 22)
                        for (let y = 0; y < height; y += 22) {
                            pen.moveTo(x-2,y); pen.lineTo(x+2,y)
                            pen.moveTo(x,y-2); pen.lineTo(x,y+2)
                        }
                    pen.stroke()
                    pen.lineCap = "round"; pen.lineJoin = "round"
                    for (const edge of diagram.paths) {
                        const a = diagram.points[edge[0]], b = diagram.points[edge[1]]
                        const ax = width*a.x/100, az = height*a.y/100, bx = width*b.x/100, bz = height*b.y/100
                        pen.beginPath(); pen.moveTo(ax,az)
                        pen.bezierCurveTo((ax+bx)/2,az,(ax+bx)/2,bz,bx,bz)
                        pen.strokeStyle = "#1e2c29"; pen.lineWidth = 7; pen.stroke()
                        pen.strokeStyle = "#cdb98e"; pen.lineWidth = 2.8; pen.stroke()
                    }
                }
            }
            Repeater {
                model: atlas.points
                delegate: Button {
                    id: pin
                    required property var modelData
                    required property int index
                    readonly property bool guideAction: true
                    objectName: "atlasPoint" + index
                    x: plot.width*modelData.x/100-width/2
                    y: plot.height*modelData.y/100-height/2
                    width: atlas.tv ? 46 : 38; height: width
                    text: (index+1).toString()
                    Accessible.name: text + ". " + modelData.name
                    Accessible.description: modelData.note
                    function activate() { clicked() }
                    focusPolicy: Qt.StrongFocus; hoverEnabled: true
                    ToolTip.visible: hovered; ToolTip.text: modelData.name
                    onClicked: atlas.chosen = index
                    background: Item {
                        Rectangle {
                            anchors.centerIn: parent; width: parent.width-10; height: width; radius: width/2
                            color: pin.index === atlas.chosen ? "#f7e7bf" : "#304943"
                            border.width: pin.activeFocus ? 3 : 1.5
                            border.color: pin.activeFocus ? "white" : "#dacba9"
                        }
                    }
                    contentItem: Text {
                        text: pin.text; color: pin.index === atlas.chosen ? "#263832" : "#fcf3da"
                        font.family: "Georgia"; font.bold: true; font.pixelSize: atlas.tv ? 20 : 16
                        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                    }
                }
            }
            Rectangle {
                visible: !!atlas.selected.name
                width: Math.min(plot.width, mapName.implicitWidth + 14); height: mapName.implicitHeight + 4
                x: Math.max(0, Math.min(plot.width - width, plot.width * (atlas.selected.x || 0) / 100 - width/2))
                y: plot.height * (atlas.selected.y || 0) / 100 +
                   ((atlas.selected.y || 0) > 55 ? -height-17 : 17)
                color: "#273a37"; radius: 2
                Text {
                    id: mapName; anchors.centerIn: parent; text: atlas.selected.name
                    color: "#fff1cb"; font.family: "Georgia"; font.pixelSize: atlas.tv ? 17 : 14
                }
            }
        }
    }
    Rectangle {
        Layout.fillWidth: true; color: "#eee9da"
        implicitHeight: key.implicitHeight + 24
        ColumnLayout {
            id: key
            anchors.left: parent.left; anchors.right: parent.right; anchors.margins: 14
            anchors.verticalCenter: parent.verticalCenter; spacing: 4
            Text {
                Layout.fillWidth: true; text: (atlas.chosen+1) + "   " + atlas.selected.name
                color: atlas.accent; font.family: "Georgia"; font.pixelSize: atlas.tv ? 26 : 21
                wrapMode: Text.WordWrap; Accessible.role: Accessible.Heading
            }
            Text {
                Layout.fillWidth: true; text: atlas.selected.note
                color: "#343e36"; font.family: "Segoe UI"; font.pixelSize: atlas.tv ? 21 : 16
                wrapMode: Text.WordWrap; Accessible.role: Accessible.StaticText
            }
        }
    }
    Flow {
        Layout.fillWidth: true
        spacing: 4
        Repeater {
            model: atlas.points
            delegate: FieldGuideButton {
                required property var modelData
                required property int index
                objectName: "atlasKey" + index
                text: (index + 1) + "  " + modelData.name
                width: Math.min(implicitWidth, atlas.width)
                quiet: true; selected: index === atlas.chosen; tv: atlas.tv
                accent: atlas.accent
                onClicked: atlas.chosen = index
            }
        }
    }
}
