pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: sheet
    required property var floors
    required property var images
    required property string status
    required property int initialMapId
    required property string place
    required property color accent
    property bool tv: false
    property bool expanded: false
    signal resizeMap()
    property int index: 0
    property int pin: -1
    property bool listOpen: false
    function resetFloor() {
        index = Math.max(0, floors.findIndex(f => f.mapId === initialMapId))
        pin = -1; listOpen = false
    }
    onPlaceChanged: Qt.callLater(resetFloor)
    onInitialMapIdChanged: Qt.callLater(resetFloor)
    onIndexChanged: { pin = -1; listOpen = false }
    readonly property var floor: floors[index] || ({})
    readonly property var raster: images[floor.mapId + "." + floor.section] || null
    readonly property bool ready: !raster || (terrain.status === Image.Ready && terrain.paintedWidth > 0)
    readonly property var marks: (floor.landmarks || []).filter(p => raster && p.x >= raster.left &&
        p.z >= raster.top && p.x < raster.left+raster.width && p.z < raster.top+raster.height)
    spacing: 5
    component Button: FieldGuideButton { tv: sheet.tv; accent: sheet.accent }
    component Caption: Text {
        Layout.fillWidth: true; wrapMode: Text.WordWrap
        color: "#34443a"; font.family: "Segoe UI"; font.pixelSize: sheet.tv ? 20 : 15
        Accessible.role: Accessible.StaticText; Accessible.name: text
    }
    RowLayout {
        Layout.fillWidth: true; spacing: 4
        Button {
            objectName: "floorPrevious"; text: "‹"; Accessible.name: "Previous floor"
            visible: sheet.floors.length > 1; enabled: sheet.index > 0
            Layout.preferredWidth: sheet.tv ? 55 : 43; onClicked: sheet.index--
        }
        Button {
            objectName: "floorPicker"; Layout.fillWidth: true; Layout.minimumWidth: 0
            text: (sheet.floor.name || "") + (sheet.floors.length > 1 ? "  ▾" : "")
            detail: sheet.floors.length > 1 ? "Floor " + (sheet.index+1) + " of " + sheet.floors.length : "Floor plan"
            Accessible.name: "Choose floor. " + text; onClicked: sheet.listOpen = !sheet.listOpen
        }
        Button {
            objectName: "floorNext"; text: "›"; Accessible.name: "Next floor"
            visible: sheet.floors.length > 1; enabled: sheet.index+1 < sheet.floors.length
            Layout.preferredWidth: sheet.tv ? 55 : 43; onClicked: sheet.index++
        }
        Button {
            objectName: "floorSize"; visible: !!sheet.raster
            text: sheet.expanded ? "Fold" : "Enlarge"
            Accessible.name: sheet.expanded ? "Return to directions" : "Enlarge floor map"
            onClicked: sheet.resizeMap()
        }
    }
    Repeater {
        model: sheet.listOpen ? sheet.floors : []
        delegate: Button {
            required property int index
            required property var modelData
            objectName: "floorChoice"+index; Layout.fillWidth: true; text: modelData.name
            selected: sheet.index === index; onClicked: { sheet.index = index; sheet.listOpen = false }
        }
    }
    Rectangle {
        Layout.fillWidth: true; visible: !!sheet.raster; color: "#20332f"
        implicitHeight: Math.max(sheet.tv ? 210 : 165, Math.min(sheet.expanded ? 550 : sheet.tv ? 370 : 290,
            sheet.raster ? (width-24)*sheet.raster.height/sheet.raster.width + 24 : 0))
        Image {
            id: terrain; objectName: "floorRaster"
            anchors.fill: parent; anchors.margins: 12; smooth: false
            source: sheet.raster ? sheet.raster.url : ""; fillMode: Image.PreserveAspectFit
            Accessible.role: Accessible.Graphic
            Accessible.name: (sheet.floor.name || "") + ", original game floor plan"
        }
        Repeater {
            model: sheet.marks
            delegate: Rectangle {
                required property int index
                required property var modelData
                width: sheet.tv ? 23 : 19; height: width; radius: width/2
                x: terrain.x + (terrain.width-terrain.paintedWidth)/2 +
                   ((modelData.x-sheet.raster.left+0.5)/sheet.raster.width)*terrain.paintedWidth - width/2
                y: terrain.y + (terrain.height-terrain.paintedHeight)/2 +
                   ((modelData.z-sheet.raster.top+0.5)/sheet.raster.height)*terrain.paintedHeight - height/2
                color: index === sheet.pin ? "#fff7db" : "#793e32"; border.color: "#fff2cf"; border.width: 1
                Text { anchors.centerIn: parent; color: parent.index === sheet.pin ? "#272f26" : "white"
                    text: parent.index+1; font.bold: true; font.pixelSize: sheet.tv ? 14 : 12 }
                TapHandler { onTapped: sheet.pin = parent.index }
            }
        }
    }
    Flow {
        Layout.fillWidth: true; spacing: 5; visible: sheet.marks.length > 0
        Repeater {
            model: sheet.marks
            delegate: Button {
                required property int index
                required property var modelData
                objectName: "floorMark"+index; text: (index+1) + "  " + modelData.name
                quiet: true; selected: sheet.pin === index; width: Math.min(implicitWidth,sheet.width)
                onClicked: sheet.pin = index
            }
        }
    }
    Caption { visible: !!sheet.raster
        text: "Sand · floor     Ink · barrier or outside" +
              (sheet.floor.mapId >= 512 ? "     Coral · exit     Jade · crossing" : "")
    }
    Caption {
        visible: !sheet.raster && sheet.floors.length > 0
        text: sheet.status === "loading" ? "Reading floor plans from your imported disc…"
            : sheet.status === "ready" ? "This floor could not be read from the selected edition."
            : "Import the supported US disc to see its floor plans."
    }
}
