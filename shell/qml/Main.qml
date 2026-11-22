import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ApplicationWindow {
    id: root
    width: 1120
    height: 720
    minimumWidth: 555
    minimumHeight: 450
    visible: true
    title: "BoF Atelier"
    color: ground

    property var model: JSON.parse(player.model)
    property var journey: model.journeys[model.game] || {step:"archive", label:"Archive needed"}
    property bool iii: model.game === "bof3"
    property bool lab: model.channel === "lab"
    property bool tv: !!model.tv
    property bool small: width < 800
    property bool shortWindow: height <= 790
    property bool busy: !!model.job.phase || model.playing
    readonly property bool artworkReady: model.page === "Journey" ? campaignPanel.artworkReady
                                        : model.page === "Field guide" ? guideView.artworkReady : true
    property bool details: false
    property string panelMode: ""
    property string lastLaunch: ""
    property var launchFocus: null
    property bool gameplayControls: false
    property string previewUrl: ""
    property string previewText: ""
    property string restoreId: ""
    property string shortcutId: "quick"
    property string activeStep: journey.step
    property string currentSheet: panelMode === "setup" ? activeStep : panelMode
    readonly property string labRoute: journey.campaign?.route === "reference" ? "continue" : journey.labStock ? "stock" : journey.reference ? "reference" : ""
    readonly property string preferredRoute: activeStep === "ready" ? "play" : labRoute
    readonly property var currentCampaign: preferredRoute === "play" ? journey.stockCampaign : journey.campaign
    property alias primary: campaignPanel.primaryButton
    property color ground: "#f7f4ea"
    property color surface: "#fffcf4"
    property color raised: iii ? "#e5eada" : "#efe2d3"
    property color line: "#c9c8b8"
    property color ink: "#242e29"
    property color muted: "#49594f"
    property color accent: iii ? "#285640" : "#793e32"
    property color buttonInk: "#fff9e9"
    property color focusColor: "#a8441b"
    property int reading: tv ? 21 : 16
    property var focusBeforePanel: null

    onActiveChanged: player.perform("focus", JSON.stringify(active))
    onClosing: event => {
        if (model.guideReading) {
            event.accepted = false
            leaveBook()
        }
    }

    function act(name, value) {
        return player.perform(name, JSON.stringify(value === undefined ? null : value))
    }
    function view(name) {
        lastLaunch = ""
        previewUrl = ""
        previewText = ""
        act("page", name)
        viewport.contentItem.contentY = 0
        Qt.callLater(function () {
            if (name === "Journey") primary.forceActiveFocus()
            else if (name === "Workshop" || name === "Lab") settingsNav.forceActiveFocus()
            else if (root.model.input.connected && remapRows.itemAt(0)) remapRows.itemAt(0).forceActiveFocus()
            else tvButton.forceActiveFocus()
        })
    }
    function selectTitle(game) {
        previewUrl = ""
        previewText = ""
        lastLaunch = ""
        act("selectGame", game)
        if (root.model.page === "Field guide") { openBook("guide"); return }
        Qt.callLater(function () { primary.forceActiveFocus() })
    }
    function readBook(page) {
        guideView.openBook(model.game, model.record?.fingerprint || "unregistered", model.guideBranch, page || "guide")
    }
    function openBook(page) {
        act("openGuide", page || "guide")
    }
    function leaveBook() {
        if (model.guideReading) act("returnToGame")
        else view("Journey")
    }
    function padButton(name) {
        const xbox = {south:"A", east:"B", west:"X", north:"Y", start:"Menu", view:"View"}
        const playstation = {south:"Cross", east:"Circle", west:"Square", north:"Triangle", start:"Options", view:"Share"}
        const names = model.input.family === "Xbox" ? xbox : model.input.family === "PlayStation" ? playstation : {}
        if (name === "left stick") return model.input.family === "PlayStation" ? "L3" : "Left stick click"
        if (name === "right stick") return model.input.family === "PlayStation" ? "R3" : "Right stick click"
        if (names[name]) return names[name]
        return name ? name[0].toUpperCase() + name.slice(1) : ""
    }
    function openSheet(mode) {
        if (!sheet.opened) focusBeforePanel = activeFocusItem
        details = false
        panelMode = mode
        if (!sheet.opened) sheet.open()
        Qt.callLater(focusSheet)
    }
    function focusSheet() {
        if (sheet.opened && sheetPrimary.visible && sheetPrimary.enabled) sheetPrimary.forceActiveFocus()
        else if (sheet.opened) dismiss.forceActiveFocus()
    }
    function launch(route) {
        if (busy) return
        lastLaunch = route
        launchFocus = sheet.opened ? focusBeforePanel : activeFocusItem
        if (sheet.opened) sheet.close()
        if (route === "play") act("launch")
        else if (route === "integer") act("launchInteger")
        else act("openLab", route)
    }
    function playSavedCopy(action, id) {
        if (busy) return
        launchFocus = sheet.opened ? focusBeforePanel : activeFocusItem
        lastLaunch = ""
        act(action, id)
        sheet.close()
    }
    function shortcutName(action) {
        return {guide:"Field guide", quick:"Quick save", suspend:"Suspend", speed:"Hold 2×"}[action] || ""
    }
    function shortcutText(action) {
        const binding = model.shortcuts[action]
        return binding.key + ((iii || action === "guide") && binding.pad ? " / " + padButton(binding.pad) : "")
    }
    function checkpointLabel(kind) {
        return kind === "suspend" ? "Resume suspended game" : "Resume quick save"
    }
    function playAction() {
        if (busy) return
        if (model.outcome.error && lastLaunch) launch(lastLaunch)
        else if (preferredRoute) launch(preferredRoute)
        else openSheet("setup")
    }
    function statusHead() {
        if (model.playing) return "Game running"
        if (model.job.phase && lastLaunch) return "Opening game…"
        if (model.outcome.error && lastLaunch) return "The game couldn’t open"
        if (preferredRoute) return ""
        switch (activeStep) {
        case "archive": return "Game archive needed"
        case "revision": return "Archive needs review"
        case "runtime": return "Playback setup needed"
        case "bios": return "Needs a PlayStation BIOS"
        case "options": return "Playback needs setup"
        default: return ""
        }
    }
    function statusCopy() {
        if (model.playing) return model.guideError || ("Open the Field guide with " + shortcutText("guide") + ".")
        if (model.job.phase && lastLaunch) return ""
        if (model.outcome.error && lastLaunch) return model.message
        if (preferredRoute && currentCampaign) return "Choose Load Game to continue from the memory card."
        if (preferredRoute) return lab || preferredRoute !== "play" ? "Uses separate Lab saves." : ""
        switch (activeStep) {
        case "archive": return "Add the local archive you already have. Atelier checks the game and its tracks."
        case "revision": return "Atelier found an import, but could not verify the edition needed for playback. Choose the supported original archive."
        case "runtime": return "Your archive is ready. Set up playback for this PC."
        case "bios": return "Add a compatible North American PlayStation system file."
        case "options": return "Set up a compatible player for this disc."
        default: return lab ? "This session uses Lab settings and saves." : "Original rules, artwork and music."
        }
    }
    function mainLabel() {
        if (model.playing) return "Playing"
        if (model.job.phase && lastLaunch) return "Opening game"
        if (model.outcome.error && lastLaunch) return "Try again"
        if (activeStep === "archive" || activeStep === "revision") return "Add game"
        if (currentCampaign) return lab || preferredRoute !== "play" ? "Continue in Lab" : "Continue"
        if (preferredRoute === "play") return lab ? "Play in Lab" : "Play"
        if (preferredRoute) return "Play in Lab"
        return "Set up to play"
    }
    function sheetTitle() {
        switch (currentSheet) {
        case "archive": case "revision": return "Add a game archive"
        case "runtime": return "Set up playback"
        case "bios": return "Add a PlayStation BIOS"
        case "firmwareHelp": return "BIOS options"
        case "options": case "lab": return "Lab playback"
        case "saves": return "Saves"
        case "shortcut": return shortcutName(shortcutId)
        case "controller":
            if (!model.input.connected) return "Connect a controller"
            if (model.input.proposal) return "Use " + padButton(model.input.proposal[1]) + " to select?"
            if (model.input.capture) return "Press the new Select button"
            return "Controller"
        case "restore": return "Restore to a separate Lab branch"
        case "masterFirst": return "Choose the first master"
        case "masterSecond": return "Choose the second master"
        case "ready": return "Ready to play"
        default: return "Set up " + model.title
        }
    }
    function sheetCopy() {
        switch (currentSheet) {
        case "archive": case "revision": return "Choose the archive you already have. Atelier identifies the game and checks every track."
        case "runtime": return journey.cachedPackage ? "The player is available on this PC. Prepare it to continue." : "Choose the official ZIP or a compatible installation on this PC."
        case "bios": return "Choose a North American PlayStation BIOS you already have, as a file or ZIP."
        case "firmwareHelp": return labRoute ? "Play now with the local replacement BIOS in Lab. Lab keeps its own saves." :
            "This route needs a compatible BIOS. You can reuse one from your own installation or copy it from your console."
        case "options": case "lab": return journey.campaign ? "Continue from a verified Lab memory card, or start a new branch." :
            journey.reference || journey.labStock ? "Research Lab keeps its own memory cards and settings. Start a separate campaign here." :
            "Prepare the reviewed Lab player to try this game in a separate campaign."
        case "saves": return "Atelier backs up in-game saves when you close a managed game."
        case "shortcut": return shortcutId === "guide" ? "Press and release to open the guide. Press again to return." : "Choose the keys or buttons to use in the game."
        case "controller":
            if (!model.input.connected) return "Plug in a USB controller. Its name will appear here."
            if (model.input.proposal) return "Press " + padButton(model.input.bindings.select) + " to confirm."
            if (model.input.capture) return "Press the button you want to use to select in this launcher."
            return model.input.name + " connected. " + padButton(model.input.bindings.select) + " selects in the launcher."
        case "restore": return "Open a separate copy in Lab. Choose Load Game in the game."
        case "ready": return "Your game, playback files and BIOS are ready."
        default: return ""
        }
    }
    function sheetLabel() {
        switch (currentSheet) {
        case "archive": case "revision": return "Choose game archive"
        case "runtime": return journey.cachedPackage ? "Prepare playback" : "Choose official ZIP"
        case "bios": return "Choose BIOS file"
        case "firmwareHelp": return labRoute ? "Play in Lab" : "Back to setup"
        case "options": case "lab": return journey.campaign ? "Continue this Lab campaign" :
            journey.reference || journey.labStock ? "Start a separate Lab campaign" : "Set up Lab preview"
        case "saves": return "Back up a save folder"
        case "shortcut": return "Done"
        case "controller":
            if (!model.input.connected) return "Back to games"
            if (model.input.proposal) return "Keep " + padButton(model.input.proposal[1])
            if (model.input.capture) return "Cancel"
            return "Remap gameplay"
        case "restore": return journey.reference ? "Restore and play in Lab" : "Restore a copy"
        case "ready": return "Play " + model.title
        default: return "Back to library"
        }
    }
    function sheetAction() {
        switch (currentSheet) {
        case "archive": case "revision": player.pick("archive"); break
        case "runtime": if (journey.cachedPackage) act("prepare"); else player.pick("runtimePackage"); break
        case "bios": player.pick("firmware"); break
        case "firmwareHelp": if (labRoute) launch(labRoute); else { panelMode = "setup"; focusSheet() } break
        case "options": case "lab":
            if (labRoute) launch(labRoute)
            else player.pick("labPackage")
            break
        case "saves": player.pick("capture"); break
        case "controller":
            if (!model.input.connected) sheet.close()
            else if (model.input.proposal) {
                act("acceptBinding")
                sheet.close()
                Qt.callLater(function () { primary.forceActiveFocus() })
            } else if (model.input.capture) act("discardBinding")
            else { gameplayControls = true; sheet.close(); root.view("Controls") }
            break
        case "restore":
            if (journey.reference) playSavedCopy("playBackup", restoreId)
            else { act("restoreCards", restoreId); panelMode = "saves" }
            break
        case "ready": launch("play"); break
        default: sheet.close()
        }
    }
    function collect(item, buttons) {
        if (!item.visible || !item.enabled) return
        if (item.walkable === true) buttons.push(item)
        else for (let child of item.children) collect(child, buttons)
    }
    function navigate(key) {
        if (model.page === "Field guide" && !sheet.opened) {
            if (guideView.navigate(key === "select" ? "confirm" : key)) return
        }
        if (model.playing) return
        if (key === "back") {
            if (model.input.capture || model.input.proposal) act("discardBinding")
            else if (sheet.opened && !busy) sheet.close()
            else if (!sheet.opened && model.page !== "Journey") view("Journey")
            return
        }
        let focused = activeFocusItem
        if (!focused || focused.walkable !== true) {
            if (sheet.opened) focusSheet()
            else primary.forceActiveFocus()
            return
        }
        if (key === "select") { if (focused.enabled) focused.clicked(); return }
        let choices = []
        collect(sheet.opened ? sheet.contentItem : root.contentItem, choices)
        let p = focused.mapToItem(root.contentItem, focused.width/2, focused.height/2)
        let vert = key === "up" || key === "down"
        let sign = key === "left" || key === "up" ? -1 : 1
        let best = null, score = Infinity
        for (let candidate of choices) {
            if (candidate === focused) continue
            let q = candidate.mapToItem(root.contentItem, candidate.width/2, candidate.height/2)
            let distance = sign * (vert ? q.y-p.y : q.x-p.x)
            let cross = Math.abs(vert ? p.x-q.x : p.y-q.y)
            if (distance > 3 && distance+cross*3 < score) {
                best = candidate
                score = distance+cross*3
            }
        }
        if (!best) return
        best.forceActiveFocus(Qt.TabFocusReason)
        if (!sheet.opened) {
            let pt = best.mapToItem(content, 0, 0)
            let f = viewport.contentItem
            if (pt.y > 0 && (pt.y < f.contentY || pt.y + best.height > f.contentY + viewport.height))
                f.contentY = Math.max(0, pt.y - 50)
        }
    }
    Connections {
        target: player
        function onChanged() {
            let previous = root.activeStep
            const lastBook = root.model.guideRequest
            const hadProposal = !!root.model.input.proposal
            root.model = JSON.parse(player.model)
            if (root.model.page === "Field guide" && root.model.guideRequest !== lastBook)
                Qt.callLater(function () { root.readBook(root.model.guideEntry) })
            if (root.model.page === "Controls" && !hadProposal && !!root.model.input.proposal) {
                Qt.callLater(function () { if (keepMapping.visible) keepMapping.forceActiveFocus() })
            }
            if (root.model.outcome.returned && !root.model.outcome.error) root.lastLaunch = ""
            if (sheet.opened && root.panelMode === "archive" && root.model.outcome.imported) {
                root.panelMode = "setup"
                Qt.callLater(root.focusSheet)
            } else if (sheet.opened && root.panelMode === "setup" && previous !== root.activeStep) {
                Qt.callLater(root.focusSheet)
            }
        }
        function onMove(action) { root.navigate(action) }
        function onReturned() {
            root.raise()
            root.requestActivate()
            Qt.callLater(function () {
                if (root.launchFocus && root.launchFocus.visible && root.launchFocus.enabled)
                    root.launchFocus.forceActiveFocus()
                else if (primary.visible) primary.forceActiveFocus()
            })
        }
    }
    Shortcut { sequence:"Left"; onActivated:root.navigate("left") }
    Shortcut { sequence:"Right"; onActivated:root.navigate("right") }
    Shortcut { sequence:"Up"; onActivated:root.navigate("up") }
    Shortcut { sequence:"Down"; onActivated:root.navigate("down") }
    Shortcut { sequence:"Escape"; onActivated:root.navigate("back") }

    component Action: Button {
        id: control
        property bool walkable: true
        property bool strong: false
        property bool selected: false
        property bool outlined: false
        focusPolicy: Qt.StrongFocus
        opacity: enabled ? 1 : 0.58
        padding: root.tv ? 14 : 11
        implicitHeight: Math.max(root.tv ? 54 : 44, contentItem.implicitHeight + topPadding + bottomPadding)
        Accessible.name: text
        contentItem: Text {
            text: control.text
            font.family:"Segoe UI"
            font.pixelSize:root.tv ? 18 : 15
            font.weight:Font.DemiBold
            color:control.strong ? root.buttonInk : control.hovered || control.selected || control.outlined ? root.ink : root.muted
            verticalAlignment:Text.AlignVCenter
            wrapMode:Text.WordWrap
            textFormat:Text.PlainText
        }
        background: Rectangle {
            radius:2
            color:control.strong ? root.accent : control.hovered || control.selected ? root.raised : control.outlined ? root.surface : "transparent"
            border.color:control.activeFocus ? root.focusColor : control.selected ? root.accent : control.outlined ? root.line : "transparent"
            border.width:control.activeFocus ? 2 : 1
        }
        Keys.onReturnPressed: event => { if (enabled && !event.isAutoRepeat) clicked(); event.accepted = true }
        Keys.onEnterPressed: event => { if (enabled && !event.isAutoRepeat) clicked(); event.accepted = true }
    }
    component Copy: Text {
        Layout.fillWidth:true
        color:root.muted
        font.family:"Segoe UI"
        font.pixelSize:root.reading
        lineHeight:1.13
        wrapMode:Text.Wrap
        textFormat:Text.PlainText
    }
    component Label: Copy {
        color:root.accent
        font.pixelSize:root.tv ? 15 : 12
        font.letterSpacing:1.6
        font.weight:Font.DemiBold
    }
    component Heading: Copy {
        color:root.ink
        font.family:"Georgia"
        font.pixelSize:root.tv ? 38 : 31
    }
    component Rule: Rectangle {
        Layout.fillWidth:true
        implicitHeight:1
        color:root.line
    }
    ColumnLayout {
        anchors.fill:parent
        spacing:0
        GridLayout {
            Layout.alignment:Qt.AlignHCenter
            Layout.fillWidth:true
            Layout.maximumWidth:1320
            Layout.leftMargin:root.small ? 13 : 28
            Layout.rightMargin:root.small ? 13 : 28
            Layout.topMargin:5; Layout.bottomMargin:5
            columns:root.width < 890 ? 2 : 3
            columnSpacing:root.small ? 6 : 16; rowSpacing:0
            RowLayout {
                Layout.row:0; Layout.column:0; Layout.fillWidth:root.width < 890
                spacing:9
                Rectangle {
                    width:30; height:33; color:root.accent
                    Text { anchors.centerIn:parent; text:"A"; color:root.buttonInk; font.italic:true; font.family:"Georgia"; font.pixelSize:23 }
                    Accessible.ignored:true
                }
                Text { text:"BoF <i>Atelier</i>"; color:root.ink; font.family:"Georgia"; font.pixelSize:root.tv ? 32 : 26 }
            }
            RowLayout {
                Layout.row:root.width < 890 ? 1 : 0; Layout.column:root.width < 890 ? 0 : 1
                Layout.columnSpan:root.width < 890 ? 2 : 1
                Layout.fillWidth:true; Layout.alignment:Qt.AlignHCenter
                spacing:root.small ? 4 : 7
                Action { text:"Campaign"; selected:root.model.page === "Journey"; enabled:!root.busy; onClicked:root.view("Journey") }
                Action { id:navGuide; objectName:"navGuide"; text:"Field guide"; selected:root.model.page === "Field guide"; enabled:!root.model.job.phase && (!root.model.playing || root.model.guideAvailable); onClicked:root.openBook("guide") }
                Action { objectName:"saves"; text:"Saves"; selected:sheet.opened && root.currentSheet === "saves"; enabled:!root.busy; onClicked:root.openSheet("saves") }
                Action { id:settingsNav; text:"Settings"; selected:["Controls","Library & setup","Workshop","Lab"].includes(root.model.page); enabled:!root.busy; onClicked:root.view("Controls") }
            }
            RowLayout {
                Layout.row:0; Layout.column:root.width < 890 ? 1 : 2; Layout.alignment:Qt.AlignRight; spacing:2
                Action { objectName:"game3"; text:"III"; Accessible.name:"Breath of Fire III"; selected:root.iii; outlined:true; enabled:!root.busy; onClicked:root.selectTitle("bof3") }
                Action { objectName:"game4"; text:"IV"; Accessible.name:"Breath of Fire IV"; selected:!root.iii; outlined:true; enabled:!root.busy; onClicked:root.selectTitle("bof4") }
            }
        }
        Rule {}
        FieldGuide {
            id:guideView
            Layout.fillWidth:true; Layout.fillHeight:true
            visible:root.model.page === "Field guide"
            tv:root.tv; inSession:root.model.guideReading
            gameRunning:root.model.playing
            gameStory:root.model.guideStory || ({})
            gameStatus:root.model.guideError || root.model.guideStatus
            onExitRequested:root.leaveBook()
        }
        ScrollView {
            id: viewport
            visible:root.model.page !== "Field guide"
            Layout.fillWidth:true
            Layout.fillHeight:true
            contentWidth:availableWidth
            contentHeight:content.height + (root.shortWindow ? 26 : 58)
            clip:true
            ScrollBar.horizontal.policy:ScrollBar.AlwaysOff
            Item {
                width:viewport.availableWidth
                height:viewport.contentHeight
                ColumnLayout {
                    id: content
                    anchors.horizontalCenter:parent.horizontalCenter
                    y:root.shortWindow ? 15 : 31
                    width:Math.min(1320, parent.width * .93)
                    spacing:root.shortWindow ? 14 : 21
                    Campaign {
                        id:campaignPanel; host:root; Layout.fillWidth:true
                        visible:root.model.page === "Journey"
                    }
                    ColumnLayout {
                        visible:root.model.page === "Controls" || root.model.page === "Library & setup"
                        Layout.fillWidth:true
                        spacing:12
                        Heading { text:"Settings" }
                        RowLayout {
                            Action { id:workshopNav; text:"Workshop"; outlined:true; onClicked:root.view("Workshop") }
                            Action { id:labNav; text:"Research Lab"; outlined:true; onClicked:root.view("Lab") }
                        }
                        Rule {}
                        Heading { text:"Controller"; font.pixelSize:27 }
                        Copy { text:root.model.input.connected ? root.model.input.name + " connected" :
                            root.model.input.status || "Connect a controller, or use the keyboard." }
                        Copy { visible:!!root.model.input.last && root.model.input.connected; text:"Last input: " + root.padButton(root.model.input.last) }
                        Flow {
                            Layout.fillWidth:true
                            spacing:8
                            Action { id:tvButton; text:root.tv ? "Desktop text" : "Large TV text"; onClicked:root.act("tv"); selected:root.tv; outlined:true }
                            Action { text:"Next controller"; visible:root.model.input.count > 1; onClicked:root.act("nextDevice") }
                        }
                        RowLayout {
                            Action {
                                text:"In game"
                                selected:root.gameplayControls
                                onClicked:{ root.act("discardBinding"); root.gameplayControls = true }
                            }
                            Action {
                                text:"In Atelier"
                                selected:!root.gameplayControls
                                onClicked:{ root.act("discardBinding"); root.gameplayControls = false }
                            }
                        }
                        Copy {
                            visible:root.gameplayControls
                            text:!root.model.input.gameplayEnabled ? "Lab uses the game engine’s current controls." :
                                !root.model.input.gameplayDevice ? "Connect one recognised gamepad to remap gameplay in Lab." :
                                "These buttons apply the next time you open a Windows Lab game."
                        }
                        RowLayout {
                            visible:root.gameplayControls
                            Action { text:root.model.input.gameplayEnabled ? "Use engine controls" : "Use Atelier controls"; onClicked:root.act("toggleGameplay") }
                            Action { text:"Reset gameplay mapping"; visible:root.model.input.gameplayDevice; onClicked:root.act("resetGameplay") }
                        }
                        Action { text:"Reset Atelier mapping"; visible:root.model.input.connected && !root.gameplayControls; onClicked:root.act("resetBindings") }
                        Flow {
                            Layout.fillWidth:true
                            spacing:8
                            visible:root.gameplayControls ? root.model.input.gameplayDevice && root.model.input.gameplayEnabled : root.model.input.connected
                            Repeater {
                                id:remapRows
                                model:root.gameplayControls ? Object.keys(root.model.input.gameplay) : ["select","back","up","down","left","right"]
                                delegate:Action {
                                    required property string modelData
                                    objectName:(root.gameplayControls ? "game-binding-" : "binding-") + modelData
                                    text:modelData[0].toUpperCase() + modelData.slice(1) + "  ·  " +
                                        root.padButton((root.gameplayControls ? root.model.input.gameplay : root.model.input.bindings)[modelData])
                                    outlined:true
                                    onClicked:root.act("captureBinding", (root.gameplayControls ? "game:" : "") + modelData)
                                }
                            }
                        }
                        Copy { visible:!!root.model.input.capture; text:"Press a button for " + root.model.input.capture.replace("game:", "") + "." }
                        Copy { visible:!!root.model.input.proposal; text:root.model.input.proposal ? "Set " + root.model.input.proposal[0].replace("game:", "") + " to " + root.padButton(root.model.input.proposal[1]) + "?" : "" }
                        Flow {
                            Layout.fillWidth:true
                            visible:!!root.model.input.capture || !!root.model.input.proposal
                            Action {
                                id:keepMapping
                                objectName:"keepMapping"
                                text:"Keep mapping"
                                visible:!!root.model.input.proposal
                                strong:true
                                onClicked:{
                                    root.act("acceptBinding")
                                    if (remapRows.itemAt(0)) remapRows.itemAt(0).forceActiveFocus()
                                }
                            }
                            Action { text:"Cancel mapping"; onClicked:root.act("discardBinding") }
                        }
                        Copy {
                            visible:root.gameplayControls
                            text:root.iii ? "DuckStation pause menu: right stick click or Esc." : "Redux pause: F6. Resume: F5."
                        }
                        ColumnLayout {
                            Layout.fillWidth:true
                            visible:root.model.guideAvailable || root.model.checkpointControls
                            spacing:8
                            Rule {}
                            Heading { text:"Game shortcuts"; font.pixelSize:27 }
                            Flow {
                                Layout.fillWidth:true
                                spacing:7
                                Repeater {
                                    model:(root.model.guideAvailable ? ["guide"] : []).concat(root.model.checkpointControls ? (root.iii && root.model.preferences.fastForward ? ["quick","suspend","speed"] : ["quick","suspend"]) : [])
                                    delegate:Action {
                                        required property string modelData
                                        objectName:"shortcut-" + modelData
                                        text:root.shortcutName(modelData) + " · " + root.shortcutText(modelData)
                                        enabled:!root.busy
                                        onClicked:{ root.shortcutId = modelData; root.openSheet("shortcut") }
                                    }
                                }
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth:true
                            visible:root.iii && root.journey.labStock
                            spacing:8
                            Rule {}
                            Heading { text:"Breath of Fire III · Lab"; font.pixelSize:27 }
                            RowLayout {
                                Action {
                                    objectName:"hold2x"
                                    text:root.model.preferences.fastForward ? "Hold 2× · On" : "Hold 2× · Off"
                                    selected:root.model.preferences.fastForward
                                    onClicked:root.act("hold2x", !root.model.preferences.fastForward)
                                }
                            }
                            RowLayout {
                                Action {
                                    objectName:"presentation-original"
                                    text:"Original"
                                    selected:root.model.preferences.presentation === "original"
                                    onClicked:root.act("presentation", "original")
                                }
                                Action {
                                    objectName:"presentation-crisp"
                                    text:"Crisp Pixels"
                                    selected:root.model.preferences.presentation === "crisp"
                                    onClicked:root.act("presentation", "crisp")
                                }
                            }
                            RowLayout {
                                Layout.fillWidth:true
                                visible:!!root.model.art["bof3-original"] && !!root.model.art["bof3-crisp"]
                                Repeater {
                                    model:[{key:"original", title:"Original"}, {key:"crisp", title:"Crisp Pixels"}]
                                    delegate:ColumnLayout {
                                        required property var modelData
                                        Layout.fillWidth:true
                                        Image {
                                            source:root.model.art["bof3-" + modelData.key] || ""
                                            Layout.fillWidth:true
                                            Layout.preferredHeight:root.tv ? 134 : 98
                                            fillMode:Image.PreserveAspectFit
                                            smooth:false
                                        }
                                        Copy { text:modelData.title; horizontalAlignment:Text.AlignHCenter }
                                    }
                                }
                            }
                        }
                        Rule {}
                        Heading { text:"Library and playback"; font.pixelSize:27 }
                        Flow {
                            Layout.fillWidth:true
                            spacing:8
                            Action { text:"Change library folder"; outlined:true; enabled:!root.busy; onClicked:player.pick("library") }
                            Action { objectName:"playbackSetup"; text:"Playback setup"; outlined:true; enabled:!root.busy; onClicked:root.openSheet("setup") }
                            Action { text:"Repair local player"; outlined:true; enabled:!root.busy; onClicked:root.act("repair") }
                            Action { text:"Check again"; enabled:!root.busy; onClicked:root.act("refresh") }
                        }
                        Copy { text:root.model.library; font.pixelSize:13 }
                    }
                    ColumnLayout {
                        visible:root.model.page === "Workshop"
                        Layout.fillWidth:true
                        spacing:13
                        Label { text:root.model.title.toUpperCase() }
                        Heading { text:"Workshop" }
                        Copy { text:"Explore the original game or try an isolated change in Research Lab." }
                        Rule {}
                        Heading { text:root.iii ? "Dragon genes" : "Master growth"; font.pixelSize:27 }
                        Copy {
                            visible:root.iii || !root.model.workshop.rules
                            text:root.iii ? "Combine genes to see Ryu’s form and its AP cost." : root.model.workshop.rules?.summary || "Read the rules from the verified game archive."
                        }
                        Action { id:rulesButton; outlined:true; visible:root.iii || !root.model.workshop.rules; text:root.iii ? "Build a dragon recipe" : "Compare masters"; enabled:(root.iii || !!root.journey.verified) && !root.busy; onClicked:root.iii ? root.openBook("genes") : root.act("openRules") }
                        Flow {
                            Layout.fillWidth:true
                            visible:!root.iii && !!root.model.workshop.rules
                            spacing:6
                            Action { text:root.model.workshop.rules?.reveal ? "Hide progression names" : "Show progression names"; onClicked:root.act("ruleControl","names") }
                        }
                        ColumnLayout {
                            visible:!root.iii && !!root.model.workshop.rules
                            Layout.fillWidth:true
                            spacing:6
                            RowLayout {
                                Action { objectName:"pickMasterFirst"; text:"First · " + (root.model.workshop.rules?.first || ""); onClicked:root.openSheet("masterFirst") }
                                Action { objectName:"pickMasterSecond"; text:"Second · " + (root.model.workshop.rules?.second || ""); onClicked:root.openSheet("masterSecond") }
                            }
                            Copy { text:"Stat change per level" }
                            GridLayout {
                                columns:4
                                columnSpacing:18
                                rowSpacing:6
                                Layout.fillWidth:true
                                Label { text:"Stat" }
                                Label { text:"First" }
                                Label { text:"Second" }
                                Label { text:"Change" }
                                Repeater {
                                    model:(root.model.workshop.rules?.stats || []).flatMap(stat =>
                                        [stat.label, stat.first, stat.second, stat.difference])
                                    delegate:Copy {
                                        required property var modelData
                                        text:typeof modelData === "number" && modelData > 0 ? "+" + modelData : String(modelData)
                                    }
                                }
                            }
                        }
                        Rule {}
                        Heading { text:"Asset catalogue"; font.pixelSize:27 }
                        Copy { text:root.model.workshop.previews.length ? root.model.workshop.previews.length + " private previews" : "Browse images from your local disc." }
                        Action { outlined:true; text:root.model.workshop.previews.length ? "Verify catalogue" : "Build catalogue"; enabled:!!root.model.record && !root.busy; onClicked:root.act("catalogue") }
                        Flow {
                            Layout.fillWidth:true
                            spacing:6
                            Repeater {
                                model:root.model.workshop.previews
                                delegate:Action {
                                    required property int index
                                    required property string modelData
                                    text:modelData
                                    onClicked:{
                                        let raw = root.act("assetPreview", index)
                                        if (raw) {
                                            let asset = JSON.parse(raw)
                                            root.previewUrl = asset.url
                                            root.previewText = asset.description
                                        }
                                    }
                                }
                            }
                        }
                        Image { visible:!!root.previewUrl; source:root.previewUrl; Layout.fillWidth:true; Layout.preferredHeight:240; fillMode:Image.PreserveAspectFit; smooth:false }
                        Copy { visible:!!root.previewText; text:root.previewText }
                    }
                    ColumnLayout {
                        visible:root.model.page === "Lab"
                        Layout.fillWidth:true
                        spacing:12
                        Label { text:root.model.title.toUpperCase() }
                        Heading { text:"Research Lab" }
                        Copy { text:"Experiments use separate saves." }
                        Rule {}
                        Flow {
                            Layout.fillWidth:true
                            spacing:8
                            Action { text:"Open Lab options"; outlined:true; enabled:!!root.journey.verified && !root.busy; onClicked:root.openSheet("lab") }
                            Action { visible:root.model.integerReady; text:"Try integer scaling"; enabled:!root.busy; onClicked:root.launch("integer") }
                            Action { text:root.lab ? "Return to Play setup" : "Switch to Lab setup"; enabled:!root.busy; onClicked:{ root.act("channel", root.lab ? "play" : "lab"); root.view("Controls") } }
                        }
                    }
                    ColumnLayout {
                        visible:root.model.page === "Recovery"
                        Heading { text:"Saves and backups" }
                        Action { text:"Open recovery options"; onClicked:root.openSheet("saves") }
                    }
                    Copy {
                        visible:!sheet.opened && !!root.model.message && !(root.model.outcome.error && root.lastLaunch)
                        text:root.model.message
                        font.pixelSize:root.tv ? 18 : 14
                    }
                }
            }
        }
        Rule {}
        RowLayout {
            Layout.fillWidth:true
            Layout.leftMargin:root.width*.036
            Layout.rightMargin:root.width*.036
            Layout.preferredHeight:root.tv ? 55 : 48
            Action {
                id:controllerButton
                objectName:"controller"
                text:root.model.input.connected ? root.model.input.name : "Controller"
                enabled:!root.busy
                onClicked:root.openSheet("controller")
            }
            Item { Layout.fillWidth:true }
            Text { visible:!root.small; text:root.model.input.prompts; color:root.muted; font.family:"Segoe UI"; font.pixelSize:root.tv ? 16 : 13 }
            Action { objectName:"addGames"; visible:root.model.page !== "Field guide"; text:"+  Add games"; enabled:!root.busy; onClicked:root.openSheet("archive") }
        }
    }

    Popup {
        id: sheet
        objectName:"guidedSheet"
        width:Math.min(610, root.width - 32)
        height:Math.min(root.height - 24, sheetColumn.implicitHeight)
        anchors.centerIn:Overlay.overlay
        padding:0
        modal:true
        focus:true
        closePolicy:root.busy ? Popup.NoAutoClose : Popup.CloseOnEscape
        Overlay.modal: Rectangle { color:"#c9070d0c" }
        background:Rectangle { color:root.surface; border.color:root.line; radius:8 }
        onOpened:root.focusSheet()
        onClosed:{
            if (root.panelMode === "controller" && (root.model.input.capture || root.model.input.proposal))
                root.act("discardBinding")
            if (root.focusBeforePanel && root.focusBeforePanel.visible && root.focusBeforePanel.enabled) root.focusBeforePanel.forceActiveFocus()
        }
        contentItem:ScrollView {
            clip:true
            contentWidth:availableWidth
            contentHeight:sheetColumn.implicitHeight
            ScrollBar.horizontal.policy:ScrollBar.AlwaysOff
            ColumnLayout {
                id: sheetColumn
                width:sheet.width
                spacing:0
                RowLayout {
                    Layout.fillWidth:true
                    Layout.leftMargin:23
                    Layout.rightMargin:12
                    Layout.preferredHeight:58
                    Copy { text:root.panelMode === "controller" ? "Controls" : root.model.title }
                    Action { id:dismiss; objectName:"closeSheet"; text:"×"; Accessible.name:"Close setup"; enabled:!root.busy; onClicked:sheet.close() }
                }
                Rule {}
                ColumnLayout {
                    Layout.fillWidth:true
                    Layout.minimumWidth:0
                    Layout.margins:root.small ? 22 : 30
                    spacing:10
                    Heading { objectName:"sheetTitle"; text:root.sheetTitle(); font.pixelSize:root.tv ? 36 : 31 }
                    Copy { text:root.sheetCopy() }
                    Copy {
                        visible:!!root.model.message && !root.busy
                        text:root.model.message
                        color:root.model.outcome.error ? "#913622" : root.muted
                    }
                    Copy { visible:!!root.model.job.phase; text:root.model.job.phase || "" }
                    ProgressBar {
                        visible:!!root.model.job.phase
                        Layout.fillWidth:true
                        indeterminate:!root.model.job.total
                        value:root.model.job.total ? root.model.job.done / root.model.job.total : 0
                        palette.highlight:root.accent
                    }
                    Action { visible:!!root.model.job.cancellable; text:"Cancel"; onClicked:root.act("cancel") }
                    Repeater {
                        model:root.currentSheet === "bios" ? root.model.firmwareChoices : []
                        delegate:Action {
                            required property var modelData
                            text:"Use " + modelData.name + " · " + modelData.member
                            enabled:!root.busy
                            Layout.fillWidth:true
                            onClicked:root.act("firmwareMember",modelData.member)
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth:true
                        visible:root.currentSheet === "shortcut"
                        spacing:8
                        Label { text:"KEYBOARD" }
                        Flow {
                            Layout.fillWidth:true
                            spacing:6
                            Repeater {
                                model:root.currentSheet === "shortcut" ? root.model.shortcuts[root.shortcutId].keys : []
                                delegate:Action {
                                    required property string modelData
                                    objectName:"shortcut-key-" + modelData
                                    text:modelData
                                    selected:root.model.shortcuts[root.shortcutId].key === modelData
                                    onClicked:root.act("shortcutKey", {action:root.shortcutId, choice:modelData})
                                }
                            }
                        }
                        Label { text:"CONTROLLER"; visible:root.iii || root.shortcutId === "guide" }
                        Flow {
                            Layout.fillWidth:true
                            visible:root.iii || root.shortcutId === "guide"
                            spacing:6
                            Repeater {
                                model:root.currentSheet === "shortcut" && (root.iii || root.shortcutId === "guide")
                                    ? ["auto","none"].concat(root.model.shortcuts[root.shortcutId].buttons) : []
                                delegate:Action {
                                    required property string modelData
                                    objectName:"shortcut-pad-" + modelData
                                    text:modelData === "auto" ? "Use a free button" :
                                         modelData === "none" ? "Keyboard only" : root.padButton(modelData)
                                    selected:root.model.shortcuts[root.shortcutId].padChoice === modelData
                                    onClicked:root.act("shortcutPad", {action:root.shortcutId, choice:modelData})
                                }
                            }
                        }
                        Copy {
                            visible:(root.iii || root.shortcutId === "guide") && root.model.shortcuts[root.shortcutId].padChoice !== "none"
                            text:root.model.shortcuts[root.shortcutId].pad ?
                                "Assigned to " + root.padButton(root.model.shortcuts[root.shortcutId].pad) + "." :
                                "No free button assigned. The keyboard shortcut is available."
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth:true
                        visible:root.currentSheet === "saves" && root.model.checkpointControls
                        Label { text:"CHECKPOINTS" }
                        Copy {
                            text:"Quick save " + root.shortcutText("quick") + " · Suspend and exit " + root.shortcutText("suspend")
                        }
                        Repeater {
                            model:root.currentSheet === "saves" ? root.model.checkpoints : []
                            delegate:Action {
                                required property string modelData
                                objectName:"resume-" + modelData
                                text:root.checkpointLabel(modelData)
                                enabled:!root.busy
                                onClicked:root.playSavedCopy("resumeCheckpoint", modelData)
                            }
                        }
                        Rule {}
                    }
                    Repeater {
                        model:root.currentSheet === "bios" ? root.model.discovered : []
                        delegate:Action {
                            required property var modelData
                            text:"Use " + modelData.name
                            enabled:!root.busy
                            Layout.fillWidth:true
                            onClicked:root.act("bindDiscovered",modelData.id)
                        }
                    }
                    Repeater {
                        model:root.currentSheet === "saves" ? root.model.points : []
                        delegate:ColumnLayout {
                            required property var modelData
                            Layout.fillWidth:true
                            Rule {}
                            Copy { text:(modelData.saveTitle || modelData.campaign) +
                                    (modelData.checkpointCopy ? " · Checkpoint session" : "") +
                                    " · " + modelData.title + " UTC" }
                            Copy { text:modelData.cards + " memory cards · " + modelData.states + " emulator states" }
                            Action {
                                visible:modelData.cards > 0
                                text:"Review card backup"
                                objectName:"backup-" + modelData.id
                                enabled:!root.busy
                                onClicked:{ root.restoreId = modelData.id; root.panelMode = "restore"; root.focusSheet() }
                            }
                        }
                    }
                    Repeater {
                        model:root.currentSheet === "saves" && root.journey.reference ? root.model.restored : []
                        delegate:Action {
                            required property var modelData
                            Layout.fillWidth:true
                            objectName:"restored-" + modelData.id
                            text:"Play restored copy · " + modelData.title
                            enabled:!root.busy
                            onClicked:root.playSavedCopy("playRestored", modelData.id)
                        }
                    }
                    Copy {
                        visible:root.currentSheet === "saves" && !root.model.points.length
                        text:"There are no backups for this game yet."
                    }
                    Repeater {
                        model:["masterFirst","masterSecond"].includes(root.currentSheet) ? root.model.workshop.rules?.masters || [] : []
                        delegate:Action {
                            required property string modelData
                            required property int index
                            Layout.fillWidth:true
                            text:modelData
                            onClicked:{
                                root.act("ruleControl", {compare:root.currentSheet === "masterFirst" ? "first" : "second", id:index})
                                sheet.close()
                            }
                        }
                    }
                    Flow {
                        Layout.fillWidth:true
                        spacing:6
                        Action { id:sheetPrimary; objectName:"sheetPrimary"; text:root.sheetLabel(); strong:true; enabled:!root.busy; onClicked:root.sheetAction() }
                        Action {
                            visible:root.currentSheet === "controller" && root.model.input.connected && !root.model.input.capture && !root.model.input.proposal
                            text:"All mappings"
                            onClicked:{ sheet.close(); root.view("Controls") }
                        }
                        Action { visible:root.currentSheet === "bios"; text:"I don’t have one"; enabled:!root.busy; onClicked:root.openSheet("firmwareHelp") }
                        Action { visible:root.currentSheet === "firmwareHelp"; text:"Console backup instructions"; onClicked:Qt.openUrlExternally("https://github.com/ShendoXT/biosdumper") }
                        Action { visible:root.currentSheet === "bios"; text:"Search a folder"; enabled:!root.busy; onClicked:player.pick("discover") }
                        Action { objectName:"labFirmware"; visible:root.currentSheet === "bios" && root.lab; text:"Use verified Lab BIOS"; enabled:!root.busy; onClicked:root.act("labFirmware") }
                        Action { visible:root.currentSheet === "runtime"; text:"Use existing installation"; enabled:!root.busy; onClicked:player.pick("existingRuntime") }
                        Action { visible:root.currentSheet === "runtime" && root.journey.cachedPackage; text:"Choose another ZIP"; enabled:!root.busy; onClicked:player.pick("runtimePackage") }
                        Action { visible:root.currentSheet === "runtime"; text:"Official release"; onClicked:Qt.openUrlExternally("https://github.com/stenzek/duckstation/releases/tag/v0.1-12442") }
                        Action { visible:(root.currentSheet === "options" || root.currentSheet === "lab") && root.journey.campaign?.route === "reference"; text:"Start a new Lab campaign"; enabled:!root.busy; onClicked:root.launch("reference") }
                        Action { visible:root.currentSheet === "bios" && !!root.labRoute; text:"Play in Lab"; enabled:!root.busy; onClicked:root.launch(root.labRoute) }
                        Action { visible:root.currentSheet === "restore"; text:"Back to saves"; enabled:!root.busy; onClicked:root.openSheet("saves") }
                        Action {
                            visible:root.currentSheet === "restore" && root.journey.reference
                            text:"Restore without playing"
                            enabled:!root.busy
                            onClicked:{ root.act("restoreCards", root.restoreId); root.panelMode = "saves" }
                        }
                    }
                    Action {
                        visible:["runtime","bios","options","lab","revision"].includes(root.currentSheet) && !!root.journey.reason
                        text:root.details ? "Hide technical details" : "Technical details"
                        onClicked:root.details = !root.details
                    }
                    Copy { visible:root.details; text:root.journey.reason || "" }
                }
            }
        }
    }
    DropArea {
        anchors.fill:parent
        enabled:!root.busy
        onDropped: drop => {
            if (!drop.hasUrls) return
            let firmware = sheet.opened && root.currentSheet === "bios"
            if (!firmware && !sheet.opened) root.openSheet("setup")
            player.dropped(drop.urls, firmware ? "firmware" : "archive")
            drop.acceptProposedAction()
        }
    }
    Component.onCompleted:Qt.callLater(function () { if (root.model.page === "Journey") primary.forceActiveFocus(); else if (root.model.page === "Field guide") root.readBook(root.model.guideEntry) })
}
