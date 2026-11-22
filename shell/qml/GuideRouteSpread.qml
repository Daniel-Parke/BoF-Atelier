pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: spread
    required property var reader
    readonly property var sheet: reader.sheet || ({})
    readonly property var steps: sheet.steps || []
    readonly property var diagram: sheet.id ? fieldGuide.routeDiagram(sheet.id) : ({})
    readonly property bool stacked: reader.routeExpanded || width < (reader.tv ? 910 : 720)
    readonly property int chosen: reader.selectedStep - 1
    readonly property var scopedItems: (reader.stop.items || []).filter(belongs)
    readonly property var scopedEnemies: (reader.stop.encounters || []).filter(belongs)
    function belongs(row) { return !reader.area || (row.areaIds || []).includes(reader.area.id) }
    function choose(key) {
        reader.selectedStep = key
        if (reader.routeExpanded) mapViewport.showPin()
    }
    spacing: reader.tv ? 16 : 11
    component Copy: Text {
        Layout.fillWidth: true; color: spread.reader.ink
        wrapMode: Text.WordWrap; textFormat: Text.PlainText
        font.family: "Segoe UI"; font.pixelSize: spread.reader.bodySize
        lineHeight: 1.17; Accessible.role: Accessible.StaticText; Accessible.name: text
    }
    component Section: Copy {
        font.family: spread.reader.displayFace; font.pixelSize: spread.reader.tv ? 30 : 26
        Accessible.role: Accessible.Heading
    }
    component Action: FieldGuideButton { accent: spread.reader.accent; tv: spread.reader.tv }
    Rectangle {
        visible: !!spread.sheet.warning; Layout.fillWidth: true
        implicitHeight: caution.implicitHeight + 18; color: "#f4e4c6"
        Rectangle { width: 4; height: parent.height; color: "#974123" }
        ColumnLayout {
            id: caution
            anchors.left: parent.left; anchors.right: parent.right; anchors.margins: 14
            anchors.verticalCenter: parent.verticalCenter; spacing: 2
            Copy { text: spread.sheet.warningLabel || "Missable treasure"; color: "#722e1b"; font.weight: Font.DemiBold }
            Copy { text: spread.sheet.warning || "" }
        }
    }
    Action {
        visible: !!spread.sheet.opening; objectName: "damEngines"
        text: spread.sheet.opening?.title || ""
        selected: spread.reader.enginesOpen
        Accessible.checkable: true; Accessible.checked: selected
        quiet: true; onClicked: spread.reader.enginesOpen = !spread.reader.enginesOpen
    }
    Repeater {
        model: spread.sheet.opening && spread.reader.enginesOpen ? spread.sheet.opening.steps : []
        delegate: Copy {
            required property int index; required property string modelData
            objectName: "routeOpeningStep" + (index + 1)
            text: (index + 1) + ".  " + modelData
        }
    }
    GridLayout {
        Layout.fillWidth: true; columns: spread.stacked ? 1 : 2
        columnSpacing: spread.reader.tv ? 28 : 20; rowSpacing: 15
        ColumnLayout {
            Layout.fillWidth: true; Layout.preferredWidth: 510; Layout.minimumWidth: 0; Layout.alignment: Qt.AlignTop
            spacing: 7
            RowLayout {
                Layout.fillWidth: true; spacing: 7
                Section {
                    objectName: "routeLandmark"; Layout.minimumWidth: 0
                    text: spread.sheet.mapTitle || spread.sheet.area || ""
                }
                Action {
                    visible: !!spread.diagram.url; objectName: "expandRouteMap"
                    text: spread.reader.routeExpanded ? "Close large map" : "Enlarge map"
                    onClicked: {
                        spread.reader.routeExpanded = !spread.reader.routeExpanded
                        Qt.callLater(() => { mapViewport.showPin(); spread.reader.focusNamed("expandRouteMap") })
                    }
                }
            }
            Rectangle {
                visible: !!spread.diagram.url; Layout.fillWidth: true
                implicitHeight: Math.ceil((width-2) / (spread.diagram.ratio || 1.95)) + 2
                color: "#e4d6b8"; border.color: "#a69674"; clip: true
                Flickable {
                    id: mapViewport
                    anchors.fill: parent; anchors.margins: 1; clip: true
                    contentWidth: spread.reader.routeExpanded ? Math.max(width, spread.reader.tv ? 1000 : 800) : width
                    contentHeight: contentWidth / (spread.diagram.ratio || 1.95)
                    boundsBehavior: Flickable.StopAtBounds
                    function showPin(){
                        const pin = (spread.diagram.pins || []).find(p => p.key === spread.reader.selectedStep)
                        if (!pin) return
                        contentX = Math.max(0,Math.min(contentWidth-width, contentWidth*pin.x-width/2))
                        contentY = Math.max(0,Math.min(contentHeight-height, contentHeight*pin.y-height/2))
                    }
                    Image {
                        width: mapViewport.contentWidth; height: mapViewport.contentHeight
                        objectName: "routeIllustration"; fillMode: Image.Stretch; smooth: true; mipmap: true
                        source: spread.diagram.url || ""
                        Accessible.role: Accessible.Graphic; Accessible.name: spread.sheet.mapAlt || ""
                    }
                    Repeater {
                        model: spread.diagram.pins || []
                        delegate: Button {
                            id: point
                            required property var modelData
                            readonly property bool guideAction: true
                            readonly property var step: spread.steps.find(s => s.key === modelData.key) || ({})
                            objectName: "atlasPoint" + (modelData.key-1)
                            width: Math.max(32,Math.min(56,mapViewport.contentWidth*.054)); height: width
                            x: modelData.x*mapViewport.contentWidth-width/2; y: modelData.y*mapViewport.contentHeight-height/2
                            focusPolicy: Qt.StrongFocus; hoverEnabled: true
                            Accessible.name: qsTr("Step %1. %2").arg(modelData.key).arg(step.title || "")
                            Accessible.checkable: true; Accessible.checked: spread.reader.selectedStep === modelData.key
                            function activate() { clicked() }
                            onClicked: spread.choose(modelData.key)
                            Keys.onReturnPressed: event => { if (!event.isAutoRepeat) activate(); event.accepted=true }
                            Keys.onEnterPressed: event => { if (!event.isAutoRepeat) activate(); event.accepted=true }
                            contentItem: Item {}
                            background: Item {
                                Rectangle {
                                    visible: point.activeFocus || point.hovered || spread.reader.selectedStep === point.modelData.key
                                    anchors.centerIn: parent
                                    width: Math.max(19, mapViewport.contentWidth * .045); height: width; radius: width/2
                                    color: "transparent"; border.width: point.activeFocus ? 4 : 2
                                    border.color: point.activeFocus ? "#005a79" : "#773a1e"
                                }
                            }
                        }
                    }
                }
            }
            Copy {
                visible: !!spread.diagram.url; color: spread.reader.muted; font.pixelSize: spread.reader.tv ? 17 : 14
                text: (spread.sheet.mapKind || "Route sketch") + " · not to scale"
            }
            Copy { visible: !spread.diagram.url; text: spread.sheet.mapAlt || "" }
        }
        ColumnLayout {
            Layout.fillWidth: true; Layout.preferredWidth: 315; Layout.minimumWidth: 0; Layout.alignment: Qt.AlignTop
            spacing: 2
            Copy {
                text: spread.sheet.entry || ""; font.pixelSize: spread.reader.tv ? 20 : 16
                font.weight: Font.DemiBold; color: spread.reader.accent
            }
            Repeater {
                model: spread.steps
                delegate: ColumnLayout {
                    required property var modelData
                    id: direction; Layout.fillWidth: true; spacing: 0
                    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#c7bca5" }
                    Action {
                        objectName: "routeDirection"+direction.modelData.key
                        text: direction.modelData.key + ".  " + direction.modelData.title
                        detail: (direction.modelData.optional ? "Optional detour" : "") +
                                (selected || spread.reader.stepOpen ? (direction.modelData.optional ? "\n" : "") + direction.modelData.body : "")
                        Layout.fillWidth: true; quiet: true
                        selected: spread.reader.selectedStep === direction.modelData.key
                        Accessible.checkable: true; Accessible.checked: selected
                        onClicked: spread.choose(direction.modelData.key)
                    }
                }
            }
            Action {
                objectName: "guideStep"; text: spread.reader.stepOpen ? "Show selected step" : "Read all steps"
                quiet: true; onClicked: spread.reader.stepOpen = !spread.reader.stepOpen
            }
        }
    }
    Flow {
        Layout.fillWidth: true; spacing: 6
        Action {
            objectName: "workedFloors"; visible: spread.reader.visibleFloors.length > 0
            text: spread.reader.readingFloor ? "Close floor landmarks" : "Floor landmarks"
            selected: spread.reader.readingFloor
            onClicked: { spread.reader.readingFloor = !spread.reader.readingFloor; spread.reader.mapExpanded = false }
        }
        Action {
            objectName: "guideHint"; text: spread.reader.hintOpen ? "Close hint" : "Give me a hint"
            quiet: true; onClicked: spread.reader.hintOpen = !spread.reader.hintOpen
        }
    }
    Copy { visible: spread.reader.hintOpen; text: (spread.reader.area || spread.reader.stop).hint || "" }
    Action {
        visible: !!spread.sheet.after; text: spread.reader.afterOpen ? "Close the exit directions" : (spread.sheet.after?.title || "")
        quiet: true; onClicked: spread.reader.afterOpen = !spread.reader.afterOpen
    }
    Copy { visible: !!spread.sheet.after && spread.reader.afterOpen; text: (spread.sheet.after?.steps || []).join("\n\n") }
}
