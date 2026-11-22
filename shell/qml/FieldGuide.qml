pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window
import "../../design/field-guide/content.js" as Book

FocusScope {
    id: viewer
    objectName: "fieldGuideReader"
    property bool tv: false
    property bool inSession: false
    readonly property bool artworkReady: panorama.status === Image.Ready && (!floorSheet.visible || floorSheet.ready)
    property bool gameRunning: false
    property string gameStatus: ""
    property var gameStory: ({})
    property string sessionContext: ""
    property string lastSavedPlace: ""
    onGameRunningChanged: if (!gameRunning) sessionContext = ""
    signal exitRequested()

    property string game: "bof3"
    readonly property bool third: game === "bof3"
    readonly property var volume: third ? Book.volumes.iii : Book.volumes.iv
    readonly property var leaves: third ? Book.referenceLeaves.iii : Book.referenceLeaves.iv
    readonly property var book: fieldGuide.book
    readonly property var route: book.route || volume.places.map((p, i) => ({
        id: (third ? ["mine","cedar"] : ["crash","north-desert"])[i], title: p.name, region: p.chapter,
        lead: p.lead, hint: p.hint, steps: [p.step], tip: p.next, links: [volume.article.id], art: volume.theme, sources: []
    }))
    readonly property var articles: book.articles || []
    readonly property var stop: route[Math.min(place, route.length - 1)] || ({})
    readonly property var article: articles.find(e => e.id === page) || null
    readonly property var subject: page === "walk" ? stop : article
    readonly property string pageArt: subject ? subject.art : volume.theme
    readonly property bool specimenArt: pageArt.startsWith("gene-") || ["flame","frost","thunder","iv-fishing","iv-training","iv-dragon"].includes(pageArt)
    readonly property string pinId: page === "walk" ? stop.id : page
    readonly property int savedPlace: gameStory && gameStory.game === game ? route.findIndex(p => p.id === gameStory.place) : -1
    readonly property int currentPlace: fieldGuide.marker >= 0 ? fieldGuide.marker : savedPlace
    readonly property int savedFloor: page === "walk" && place === savedPlace && fieldGuide.marker < 0
                                      && gameStory.floorId !== undefined ? gameStory.floorId : -1
    property string chosenArea: ""
    readonly property var areas: stop.sectionsByArea || []
    readonly property var area: areas.find(s => s.name === chosenArea) || areas.find(s => s.firstFloor === savedFloor) || areas[0] || null
    readonly property int firstStep: area ? area.firstStep : 0
    readonly property var visibleFloors: area ? (stop.floors || []).filter(f => f.name.startsWith(area.name)) : stop.floors || []
    readonly property bool hasWarning: !!stop.warning && (!area || !!area.warning)
    readonly property bool schematicAvailable: !!stop.map && (!area || area.name === areas[0].name)
    readonly property int readableThrough: Math.max(0, currentPlace, visitedThrough)
    property int visitedThrough: 0
    property bool showLater: false
    property bool sourcesOpen: false
    property string category: ""
    property var revealedSubjects: []
    readonly property color accent: third ? "#285647" : "#793e32"
    readonly property color paper: third ? "#f7f4ea" : "#f7f2e8"
    readonly property color pale: third ? "#e6ebe0" : "#f1e4d8"
    readonly property color ink: "#212e2a"
    readonly property color muted: third ? "#4d5a50" : "#5d5248"
    readonly property int bodySize: tv ? 23 : 17
    readonly property bool narrow: width < (tv ? 870 : 695)
    readonly property var roster: fieldGuide.catalog
    readonly property var allGenes: roster.genes || Book.specimens
    readonly property var allMasters: roster.masters || Book.masterExamples
    readonly property var result: {
        const refresh = roster
        return fieldGuide.recipe(chosen, partyAllies, partyKnown)
    }
    property string page: "guide"
    property var history: []
    property var chosen: []
    property var partyAllies: []
    property bool partyKnown: false
    property int place: 0
    property bool hintOpen: false
    property bool stepOpen: false
    property string atlasSection: ""
    property bool loreOpen: false
    readonly property string activeSection: atlasSection || (stop.map || stop.floors ? "Map" : "Notes")
    property bool overview: false
    property bool mapExpanded: false
    property bool revealNames: false
    property int first: 0
    property int second: 1
    property string picker: ""
    property string notice: ""
    property string query: ""

    function openBook(id, revision, branch, initial) {
        const scope = JSON.stringify([id,revision,branch])
        const saved = gameStory && gameStory.game === id ?
                      JSON.stringify([gameStory.place, gameStory.floorId, gameStory.visitKey || ""]) : ""
        if (inSession && sessionContext === scope && (!initial || initial === "guide") &&
                (fieldGuide.marker >= 0 || lastSavedPlace === saved)) {
            Qt.callLater(function() { if (viewer.visible) landing.forceActiveFocus() })
            return
        }
        sessionContext = inSession ? scope : ""
        lastSavedPlace = saved
        history = []
        chosen = []
        partyAllies = []
        partyKnown = false
        first = 0
        second = 1
        revealNames = false
        showLater = false
        sourcesOpen = false
        visitedThrough = 0
        category = ""
        revealedSubjects = []
        query = ""
        game = id === "bof4" ? "bof4" : "bof3"
        fieldGuide.setContext(game, revision || "unregistered", branch || "default")
        place = Math.max(0, currentPlace)
        const start = known(initial) ? initial : "guide"
        setPage(start === "guide" && currentPlace >= 0 ? "walk" : start)
    }
    function known(id) {
        return ["guide","wiki","route"].includes(id) || volume.entries.concat(leaves, articles, route).some(entry => entry.id === id)
    }
    function titleOf(id) {
        if (id === "wiki") return "Field wiki"
        if (id === "route") return "Route index"
        const found = volume.entries.concat(leaves, articles, route).find(entry => entry.id === id)
        return found ? found.title : "Field guide"
    }
    function setPage(id) {
        const index = route.findIndex(p => p.id === id)
        if (index >= 0) {
            place = index
            visitedThrough = Math.max(visitedThrough, index)
        }
        page = index >= 0 ? "walk" : id
        picker = ""
        notice = ""
        hintOpen = false
        stepOpen = false
        atlasSection = ""
        overview = false
        mapExpanded = false
        chosenArea = ""
        loreOpen = false
        sourcesOpen = false
        scroller.contentY = 0
        Qt.callLater(function() {
            if (!viewer.visible) return
            landing.forceActiveFocus()
        })
    }
    function visit(id) {
        if (!known(id) || page === id || (page === "walk" && id === stop.id)) return
        history = history.concat([page === "walk" ? stop.id : page])
        if (id === "walk") place = Math.max(0, currentPlace)
        setPage(id)
    }
    function goBack() {
        if (picker) {
            picker = ""
            focusNamed("masterSlot" + lastPicker)
        } else if (page === "wiki" && category) {
            category = ""
            focusNamed("category0")
        } else if (history.length) {
            const destination = history[history.length - 1]
            history = history.slice(0, -1)
            setPage(destination)
        } else {
            exitRequested()
        }
    }
    function isAvailable(id) {
        if (showLater) return true
        const r = route.findIndex(p => p.id === id)
        if (r >= 0) return r <= readableThrough
        const a = articles.find(e => e.id === id)
        return !a || revealedSubjects.includes(a.category) || route.findIndex(p => p.id === a.unlock) <= readableThrough
    }
    function wikiRows() {
        return articles.filter(a => isAvailable(a.id) && (!category || a.category === category))
    }
    function subjectDetail(name) {
        const rows = articles.filter(a => a.category === name)
        const later = rows.filter(a => !isAvailable(a.id)).length
        return rows.length + (rows.length === 1 ? " article" : " articles") + (later ? "  ·  " + later + " for later" : "")
    }
    function openSubject(name) {
        category = name
        const rows = wikiRows()
        focusNamed(rows.length ? "wiki" + rows[0].id : "revealSubject")
    }
    function searchRows() {
        const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
        const index = volume.entries.map(e => e.id === "walk" ? Object.assign({}, e, {detail: route.length + " stops · Hints and directions", art: route[0].art}) : e)
        if (articles.length) index.splice(1,0,{id:"wiki",title:"Field wiki",detail:articles.length + " articles · Browse by subject",terms:"encyclopaedia wiki reference",art:third ? "iii-woods" : "iv-river"})
        if (!words.length) return index
        const records = index.concat(leaves, route.filter(e => isAvailable(e.id)).map(e => ({
            id:e.id,title:e.title,detail:e.region,terms:e.lead + " " + (e.landmarks || []).join(" ")
        })), articles.filter(e => isAvailable(e.id)).map(e => ({
            id:e.id,title:e.title,detail:e.category,terms:e.lead + " " + e.sections.map(s => s.title + " " + s.text).join(" ")
                + " " + (e.records || []).map(r => r.name + " " + r.where + " " + r.detail).join(" ")
        })))
        return records.filter(entry => {
            const haystack = (entry.title + " " + entry.detail + " " + entry.terms).toLowerCase()
            return words.every(word => haystack.indexOf(word) >= 0)
        })
    }
    function chooseGene(idx) {
        const next = chosen.slice()
        const pos = next.indexOf(idx)
        if (pos >= 0) next.splice(pos, 1)
        else if (next.length < 3) next.push(idx)
        else { notice = "Remove a gene before adding another."; return }
        chosen = next
        notice = ""
    }
    function changePlace(index) {
        if (index >= 0 && index < route.length && index !== place) visit(route[index].id)
    }
    property string lastPicker: ""
    function chooseMaster(slot) {
        lastPicker = slot
        picker = picker === slot ? "" : slot
        focusNamed(picker ? "masterChoice" + (slot === "A" ? first : second) : "masterSlot" + slot)
    }
    function signed(n) { return n > 0 ? "+" + n : String(n) }
    function readingActions(item, list) {
        if (!item || !item.visible || !item.enabled) return
        if (item.guideAction === true) { list.push(item); return }
        for (let i=0; i<item.children.length; i++) readingActions(item.children[i], list)
    }
    function controls() { const list = []; readingActions(viewer, list); return list }
    function showControl(item) {
        item.forceActiveFocus()
        if (item.mapToItem(scroller.contentItem, 0, 0).y < 0 || item === returnAction || item === indexAction || item === clearGeneButton) return
        const y = item.mapToItem(scroller.contentItem, 0, 0).y
        if (y < scroller.contentY + 12) scroller.contentY = Math.max(0, y-12)
        else if (y + item.height > scroller.contentY + scroller.height - 12)
            scroller.contentY = Math.max(0, Math.min(scroller.contentHeight-scroller.height, y+item.height-scroller.height+12))
    }
    function focusNamed(name) {
        Qt.callLater(function() {
            const item = controls().find(control => control.objectName === name)
            if (item) showControl(item)
        })
    }
    function approachLink(item, action) {
        if (!item || item === indexAction || item === returnAction || item === clearGeneButton || (action !== "down" && action !== "up")) return false
        const y = item.mapToItem(scroller.contentItem, 0, 0).y
        const gap = action === "down" ? y - (scroller.contentY + scroller.height) : scroller.contentY - y - item.height
        if (gap <= 0) return false
        const previous = scroller.contentY
        const distance = Math.min(gap + Math.min(item.height,60) + 12, scroller.height*0.65)
        scroller.contentY = Math.max(0, Math.min(scroller.contentHeight-scroller.height, previous + (action === "down" ? distance : -distance)))
        return Math.abs(previous - scroller.contentY) > 1
    }
    function navigate(action) {
        if (action === "back" || action === "cancel") { goBack(); return true }
        const items = controls()
        const active = items.find(item => item.activeFocus)
        if (["select", "confirm", "accept"].indexOf(action) >= 0) {
            if (active) active.activate()
            else if (items.length) {
                const target = page === "guide" ? "entrywalk" : firstAction()
                showControl(items.find(item => item.objectName === target) || items[0])
            }
            return true
        }
        if (["up", "down", "left", "right"].indexOf(action) < 0) return false
        if (!active) {
            if (action === "up" && scroller.contentY > 1) {
                scroller.contentY = Math.max(0, scroller.contentY-scroller.height*0.65)
                return true
            }
            const initial = action === "up" ? returnAction : (items.find(item => item.objectName === firstAction()) || items[0])
            if (initial && !approachLink(initial, action)) showControl(initial)
            return true
        }
        if (active === search && (action === "left" || action === "right")) return false
        const p = active.mapToItem(viewer, active.width/2, active.height/2)
        const horizontal = action === "left" || action === "right"
        const direction = action === "left" || action === "up" ? -1 : 1
        let best = null, score = Infinity
        for (const item of items) {
            if (item === active) continue
            if ((item === indexAction || item === returnAction) && active !== indexAction && active !== returnAction &&
                    (action === "down" || (action === "up" && scroller.contentY > 1))) continue
            const q = item.mapToItem(viewer, item.width/2, item.height/2)
            const along = direction * (horizontal ? q.x-p.x : q.y-p.y)
            const cross = Math.abs(horizontal ? q.y-p.y : q.x-p.x)
            if (along <= 2 || (horizontal && cross > Math.max(active.height,item.height)*0.65)) continue
            const s = along + cross * (horizontal ? 2 : 1.2)
            if (s < score) { score = s; best = item }
        }
        if (best) { if (!approachLink(best, action)) showControl(best) }
        else if (!horizontal) scroller.contentY = Math.max(0, Math.min(Math.max(0, scroller.contentHeight - scroller.height), scroller.contentY + direction * scroller.height * 0.7))
        return true
    }
    function firstAction() {
        return page === "guide" ? "guideSearch" : page === "genes" ? "gene0" :
               page === "masters" ? "masterSlotA" : page === "walk" ? "guideHint" :
               page === "route" ? "stop" + route[0].id : page === "wiki" ? (category ? "allSubjects" : "category0") :
               article ? (references.related.length ? "related" + references.related[0] : "guideSources") : "pinEntry"
    }
    Keys.onPressed: event => {
        if (event.key === Qt.Key_Escape || event.key === Qt.Key_Back) {
            goBack(); event.accepted = true
        } else if (event.key >= Qt.Key_Left && event.key <= Qt.Key_Down) {
            const names = ["left","up","right","down"]
            event.accepted = navigate(names[event.key - Qt.Key_Left])
        } else if (landing.activeFocus && (event.key === Qt.Key_Return || event.key === Qt.Key_Space)) {
            event.accepted = navigate("down")
        }
    }

    component Action: FieldGuideButton { accent: viewer.accent; tv: viewer.tv }
    component Copy: Text {
        color: viewer.ink; font.family: "Segoe UI"; font.pixelSize: viewer.bodySize
        textFormat: Text.PlainText; wrapMode: Text.WordWrap
        lineHeight: 1.12
        Accessible.role: Accessible.StaticText; Accessible.name: text
    }
    component Title: Copy {
        font.family: "Georgia"; font.pixelSize: viewer.tv ? 31 : 25
        color: viewer.accent
        Accessible.role: Accessible.Heading
    }
    component Kicker: Copy {
        color: viewer.accent; font.pixelSize: viewer.tv ? 17 : 12
        font.weight: Font.DemiBold; font.letterSpacing: 1.6
    }
    component Rule: Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#c8c7b6" }
    component SpoilerSwitch: Action {
        text: viewer.showLater ? "Hide later names" : "Show later names (spoilers)"
        quiet: true
        onClicked: {
            viewer.showLater = !viewer.showLater
            viewer.category = ""
            if (!viewer.showLater) viewer.revealedSubjects = []
        }
    }

    Rectangle { anchors.fill: parent; color: viewer.paper }
    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: topBar.implicitHeight + (viewer.tv ? 20 : 12)
            color: "#fffdf6"
            RowLayout {
                id: topBar
                anchors.fill: parent; anchors.leftMargin: viewer.narrow ? 16 : 32; anchors.rightMargin: anchors.leftMargin
                spacing: 12
                Action {
                    id: indexAction
                    objectName: "guideIndex"
                    text: viewer.page === "guide" ? "Field guide" : "‹  Field guide"
                    quiet: true
                    enabled: viewer.page !== "guide"
                    onClicked: viewer.visit("guide")
                }
                Item { Layout.fillWidth: true }
                Copy {
                    visible: viewer.inSession && !!viewer.gameStatus
                    text: viewer.gameStatus
                    Layout.maximumWidth: viewer.width * 0.28
                    font.pixelSize: viewer.tv ? 18 : 13
                    color: viewer.muted
                }
                Action {
                    id: returnAction
                    objectName: "returnToGame"
                    text: viewer.inSession ? "Return to game" : "Back to campaign"
                    primary: viewer.inSession
                    onClicked: viewer.exitRequested()
                }
            }
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#c8c7b6" }
        Flickable {
            id: scroller
            objectName: "guideScroller"
            Layout.fillWidth: true; Layout.fillHeight: true
            contentWidth: width; contentHeight: column.implicitHeight + 40
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { }
            ColumnLayout {
                id: column
                width: Math.min(scroller.width - (viewer.narrow ? 28 : 62), viewer.tv ? 1320 : 1120)
                x: (scroller.width-width)/2; y: 15
                spacing: viewer.tv ? 19 : 13
                Rectangle {
                    id: hero
                    Layout.fillWidth: true
                    implicitHeight: Math.max(heroWords.implicitHeight + 44, viewer.narrow ? 150 : viewer.subject ? 206 : viewer.page === "guide" ? 194 : 148)
                    color: viewer.pale; clip: true
                    Item {
                        id: panoramaFrame
                        anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.right: parent.right
                        width: parent.width * (viewer.narrow ? 0.48 : 0.52)
                        clip: true
                        Image {
                            id: panorama
                            objectName: "guidePanorama"
                            source: fieldGuide.plate(viewer.pageArt) || fieldGuide.plate(viewer.volume.theme)
                            width: viewer.specimenArt ? Math.min(panoramaFrame.width, panoramaFrame.height * implicitWidth / Math.max(1,implicitHeight))
                                   : Math.max(panoramaFrame.width, panoramaFrame.height * implicitWidth / Math.max(1,implicitHeight))
                            height: width * implicitHeight / Math.max(1,implicitWidth)
                            anchors.horizontalCenter: parent.horizontalCenter
                            // Keep IV's crest inside a shallow header as the window widens.
                            y: viewer.subject ? (panoramaFrame.height-height)*0.47
                                : Math.max((panoramaFrame.height-height) * (viewer.third ? 0.11 : 0.14),
                                           -height * (viewer.third ? 0.12 : 0.022))
                            fillMode: Image.PreserveAspectFit
                            Accessible.role: Accessible.Graphic
                            Accessible.name: fieldGuide.caption(viewer.pageArt) || viewer.volume.artAlt
                        }
                        Rectangle {
                            anchors.fill: parent
                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0; color: viewer.pale }
                                GradientStop { position: 0.35; color: Qt.rgba(viewer.pale.r,viewer.pale.g,viewer.pale.b,0) }
                            }
                        }
                    }
                    ColumnLayout {
                        id: heroWords
                        anchors.left: parent.left; anchors.leftMargin: viewer.narrow ? 17 : 27
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width*(viewer.narrow ? 0.52 : 0.49)
                        spacing: 6
                        Kicker { Layout.fillWidth: true; text: viewer.volume.title.toUpperCase() }
                        Title {
                            id: landing
                            objectName: "guidePageTitle"
                            text: viewer.page === "walk" ? viewer.stop.title : viewer.titleOf(viewer.page)
                            Layout.fillWidth: true
                            font.pixelSize: viewer.narrow ? (viewer.tv ? 37 : 29) : (viewer.tv ? 49 : 42)
                        }
                        Copy {
                            visible: !!viewer.subject
                            Layout.fillWidth: true
                            text: viewer.page === "walk" ? "Stop " + (viewer.place + 1) + " of " + viewer.route.length + "  ·  " + (viewer.stop.region || "")
                                  : viewer.article ? viewer.article.category : ""
                            color: viewer.muted; font.pixelSize: viewer.tv ? 18 : 14
                        }
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    visible: viewer.page === "guide"
                    columns: viewer.narrow ? 1 : 2
                    columnSpacing: viewer.tv ? 30 : 23; rowSpacing: 15
                    ColumnLayout {
                        Layout.fillWidth: true; Layout.preferredWidth: 560; Layout.alignment: Qt.AlignTop
                        spacing: 10
                        Copy {
                            Layout.fillWidth: true; visible: !viewer.book.route
                            text: "The full book could not be read. Reinstall the Player to restore it. The opening guide is available below."
                            Accessible.role: Accessible.AlertMessage
                        }
                        TextField {
                            id: search
                            objectName: "guideSearch"
                            readonly property bool guideAction: true
                            function activate() { forceActiveFocus(); Qt.inputMethod.show() }
                            Layout.fillWidth: true
                            implicitHeight: viewer.tv ? 57 : 46
                            placeholderText: viewer.third ? "Search items, enemies, genes or places…" : "Search items, enemies, masters or places…"
                            Accessible.name: "Search this field guide"
                            leftPadding: 14; rightPadding: 14
                            color: viewer.ink; placeholderTextColor: viewer.muted
                            font.family: "Segoe UI"; font.pixelSize: viewer.bodySize
                            text: viewer.query
                            onTextEdited: viewer.query = text
                            onAccepted: {
                                const rows = viewer.searchRows()
                                if (rows.length) viewer.visit(rows[0].id)
                            }
                            background: Rectangle {
                                radius: 3; color: "#fffdf5"
                                border.width: search.activeFocus ? 2 : 1
                                border.color: search.activeFocus ? "#ab521d" : "#aaa998"
                            }
                        }
                        Repeater {
                            model: viewer.searchRows()
                            delegate: Action {
                                required property var modelData
                                Layout.fillWidth: true
                                objectName: "entry" + modelData.id
                                text: modelData.title
                                detail: modelData.detail
                                art: modelData.art ? fieldGuide.plate(modelData.art) : ""
                                onClicked: viewer.visit(modelData.id)
                            }
                        }
                        Copy {
                            Layout.fillWidth: true
                            visible: viewer.searchRows().length === 0
                            text: viewer.third ? "No entries found. Try “diary” or “gene”." : "No entries found. Try “dragon” or “master”."
                        }
                        SpoilerSwitch { visible: !!viewer.query.trim() && viewer.articles.length > 0 }
                    }
                    Rectangle {
                        Layout.fillWidth: true; Layout.preferredWidth: 260; Layout.alignment: Qt.AlignTop
                        implicitHeight: readingList.implicitHeight + 35
                        color: "#fffdf6"; border.color: "#c8c7b6"
                        Rectangle { width: parent.width; height: 3; color: viewer.accent }
                        ColumnLayout {
                            id: readingList
                            x: 16; y: 16; width: parent.width-32; spacing: 8
                            Title { text: "Reading list"; Layout.fillWidth: true }
                            Action {
                                objectName: "chooseStoryPlace"; Layout.fillWidth: true
                                visible: viewer.currentPlace < 0 && viewer.articles.length > 0
                                text: "Find my place"; detail: "Choose where to pick up the walkthrough."
                                onClicked: viewer.visit("route")
                            }
                            Action {
                                visible: viewer.currentPlace >= 0
                                objectName: "openMarkedPlace"; Layout.fillWidth: true
                                text: viewer.currentPlace >= 0 ? viewer.route[viewer.currentPlace].title : ""
                                detail: fieldGuide.marker >= 0 ? "Your marked place" : viewer.gameStory.source || ""
                                onClicked: viewer.visit("walk")
                            }
                            Copy {
                                visible: !fieldGuide.pins.length
                                Layout.fillWidth: true; color: viewer.muted; font.pixelSize: viewer.tv ? 20 : 15
                                text: "Pin a page to find it here during play."
                            }
                            Repeater {
                                model: fieldGuide.pins
                                delegate: Action {
                                    required property string modelData
                                    objectName: "pinned" + modelData
                                    Layout.fillWidth: true; quiet: true
                                    text: viewer.titleOf(modelData)
                                    onClicked: viewer.visit(modelData)
                                }
                            }
                        }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    visible: viewer.page === "walk"
                    spacing: 12
                    Kicker {
                        objectName: "storyEvidence"
                        visible: !!text
                        text: viewer.place !== viewer.currentPlace ? "" : fieldGuide.marker >= 0 ? "YOUR MARKED PLACE" :
                              viewer.savedPlace >= 0 && (!viewer.area || viewer.area.name ===
                                 (viewer.areas.find(s => s.firstFloor === viewer.savedFloor) || viewer.areas[0]).name)
                                 ? (viewer.gameStory.source || "").toUpperCase() : ""
                    }
                    RowLayout {
                        visible: viewer.areas.length > 0
                        Repeater {
                            model: viewer.areas
                            delegate: Action {
                                required property var modelData
                                objectName: "routeArea"+modelData.name; text: modelData.name
                                selected: !!viewer.area && viewer.area.name === text
                                onClicked: {
                                    viewer.chosenArea = modelData.name; viewer.hintOpen = false
                                    viewer.stepOpen = false; viewer.loreOpen = false; viewer.overview = false
                                }
                            }
                        }
                    }
                    GridLayout {
                        Layout.fillWidth: true; columns: viewer.narrow ? 1 : 2
                        columnSpacing: 25; rowSpacing: 12
                        ColumnLayout {
                            visible: !viewer.mapExpanded
                            Layout.fillWidth: true; Layout.preferredWidth: 520; Layout.alignment: Qt.AlignTop
                            spacing: 11
                            Copy { Layout.fillWidth: true; font.pixelSize: viewer.bodySize+2
                                text: viewer.area ? viewer.area.lead : viewer.stop.lead || "" }
                            Rectangle {
                                visible: viewer.hasWarning
                                Layout.fillWidth: true; implicitHeight: warningCopy.implicitHeight + 20; color: "#f4e4cc"
                                Rectangle { width: 3; height: parent.height; color: "#945221" }
                                ColumnLayout {
                                    id: warningCopy
                                    anchors.left: parent.left; anchors.right: parent.right; anchors.margins: 12
                                    anchors.verticalCenter: parent.verticalCenter; spacing: 3
                                    Kicker { text: viewer.stop.warning ? viewer.stop.warning.label.toUpperCase() : "" }
                                    Copy { Layout.fillWidth: true; text: viewer.stop.warning ? viewer.stop.warning.text : "" }
                                }
                            }
                            Kicker { text: "START HERE" }
                            Title { objectName: "routeLandmark"; Layout.fillWidth: true; text: (viewer.stop.landmarks || [])[viewer.firstStep] || viewer.stop.title || "" }
                            Copy { Layout.fillWidth: true; text: (viewer.stop.steps || [])[viewer.firstStep] || "" }
                            GridLayout {
                                columns: viewer.width < 540 ? 1 : 2
                                columnSpacing: 10
                                Action {
                                    objectName: "guideHint"; text: viewer.hintOpen ? "Hide hint" : "Give me a hint"
                                    selected: viewer.hintOpen
                                    onClicked: viewer.hintOpen = !viewer.hintOpen
                                }
                                Action {
                                    objectName: "guideStep"; text: viewer.stepOpen ? "Fold route" : "Show full route"
                                    visible: !viewer.area || viewer.area.endStep > viewer.firstStep+1
                                    primary: true; onClicked: viewer.stepOpen = !viewer.stepOpen
                                }
                            }
                            Copy { Layout.fillWidth: true; visible: viewer.hintOpen; text: viewer.area ? viewer.area.hint : viewer.stop.hint || "" }
                            Repeater {
                                model: viewer.stepOpen && viewer.page === "walk" ? viewer.stop.steps.slice(viewer.firstStep+1, viewer.area ? viewer.area.endStep : undefined) : []
                                delegate: RowLayout {
                                    required property int index
                                    required property string modelData
                                    Layout.fillWidth: true; spacing: 12
                                    Kicker { Layout.alignment: Qt.AlignTop; text: (index+2).toString() }
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 3
                                        Title { Layout.fillWidth: true; text: (viewer.stop.landmarks || [])[viewer.firstStep+index+1] || "" }
                                        Copy { Layout.fillWidth: true; text: modelData }
                                    }
                                }
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true; Layout.preferredWidth: 470; Layout.minimumWidth: 0
                            Layout.alignment: Qt.AlignTop; spacing: 8
                            GridLayout {
                                Layout.fillWidth: true
                                columns: viewer.tv || viewer.width < 970 ? 2 : 4
                                columnSpacing: 4; rowSpacing: 4
                                Repeater {
                                    model: (viewer.stop.map || viewer.stop.floors ? ["Map"] : []).concat(viewer.stop.items ? ["Items"] : [],
                                        viewer.stop.encounters ? ["Enemies"] : [], ["Notes"])
                                    delegate: Action {
                                        required property string modelData
                                        objectName: "atlasTab" + modelData
                                        text: modelData; selected: viewer.activeSection === modelData
                                        Layout.fillWidth: true
                                        onClicked: { viewer.atlasSection = modelData; if (modelData !== "Map") viewer.mapExpanded = false }
                                    }
                                }
                            }
                            FloorSheet {
                                id: floorSheet; objectName: "floorSheet"; Layout.fillWidth: true
                                visible: viewer.activeSection === "Map" && !!viewer.stop.floors && !viewer.overview
                                floors: viewer.visibleFloors; images: viewer.roster.floors || ({})
                                initialMapId: viewer.area ? viewer.area.firstFloor : viewer.savedFloor
                                place: viewer.game + "/" + (viewer.stop.id || "") + "/" + (viewer.area ? viewer.area.name : "")
                                status: fieldGuide.floorStatus; accent: viewer.accent; tv: viewer.tv
                                expanded: viewer.mapExpanded
                                onResizeMap: { viewer.mapExpanded = !viewer.mapExpanded; viewer.focusNamed("floorSize") }
                            }
                            Action {
                                visible: viewer.activeSection === "Map" && viewer.schematicAvailable && !!floorSheet.raster
                                text: viewer.overview ? "View floor plans" : "View landmark diagram"; quiet: true
                                onClicked: viewer.overview = !viewer.overview
                            }
                            Title {
                                visible: viewer.activeSection === "Map" && viewer.schematicAvailable && (!floorSheet.raster || viewer.overview)
                                Layout.fillWidth: true; text: viewer.stop.map ? viewer.stop.map.title : ""
                            }
                            FieldAtlas {
                                objectName: "areaAtlas"; Layout.fillWidth: true
                                visible: viewer.activeSection === "Map" && viewer.schematicAvailable && (!floorSheet.raster || viewer.overview)
                                chart: viewer.stop.map || null; accent: viewer.accent; tv: viewer.tv
                            }
                            FieldLedger {
                                Layout.fillWidth: true; visible: ["Items","Enemies"].includes(viewer.activeSection)
                                monsters: viewer.activeSection === "Enemies"
                                records: ((monsters ? viewer.stop.encounters : viewer.stop.items) || []).filter(r => !viewer.area || r.where.includes(viewer.area.name))
                                accent: viewer.accent; tv: viewer.tv
                            }
                            Action {
                                visible: ["Items","Enemies"].includes(viewer.activeSection)
                                objectName: "openAtlasArticle"; quiet: true
                                text: viewer.activeSection === "Items" ? "Open in item ledger  ›" : "Open in bestiary  ›"
                                onClicked: viewer.visit(viewer.stop.id + (viewer.activeSection === "Items" ? "-items" : "-encounters"))
                            }
                            Copy { Layout.fillWidth: true; visible: viewer.activeSection === "Notes"; text: viewer.area ? viewer.area.tip : viewer.stop.tip || "" }
                            Action {
                                visible: viewer.activeSection === "Notes" && !!viewer.stop.lore && (!viewer.area || !!viewer.area.lore)
                                objectName: "guideLore"; quiet: true
                                text: viewer.loreOpen ? "Close field note" : "Did you know?"
                                onClicked: viewer.loreOpen = !viewer.loreOpen
                            }
                            Copy { Layout.fillWidth: true; visible: viewer.activeSection === "Notes" && viewer.loreOpen; text: viewer.stop.lore || "" }
                        }
                    }
                        Image {
                            objectName: "guideFieldFrame"
                            readonly property string frame: fieldGuide.photos[viewer.place] || ""
                            visible: !!frame
                            Layout.preferredWidth: viewer.narrow ? 227 : 300
                            Layout.preferredHeight: viewer.narrow ? 170 : 225
                            Layout.alignment: Qt.AlignTop | (viewer.narrow ? Qt.AlignLeft : Qt.AlignRight)
                            source: frame; fillMode: Image.PreserveAspectFit
                            horizontalAlignment: viewer.narrow ? Image.AlignLeft : Image.AlignRight
                            Accessible.name: (viewer.stop.title || "") + ", gameplay illustration"
                            Accessible.role: Accessible.Graphic
                        }
                    Rule { }
                    GridLayout {
                        Layout.fillWidth: true; columns: viewer.narrow ? 1 : 2; rowSpacing: 8; columnSpacing: 10
                        Action {
                            objectName: "guideRoute"; Layout.fillWidth: true
                            text: "Route index"; quiet: true; onClicked: viewer.visit("route")
                        }
                        Action {
                            objectName: "guideReadAhead"; Layout.fillWidth: true
                            visible: viewer.place + 1 < viewer.route.length
                            text: "Read the next stop  ›"
                            onClicked: viewer.changePlace(viewer.place + 1)
                        }
                        Action {
                            objectName: "guideMark"; Layout.fillWidth: true; quiet: true
                            visible: fieldGuide.marker !== viewer.place
                            text: "Set my place here"
                            onClicked: { fieldGuide.setMarker(viewer.place); viewer.focusNamed("guideRoute") }
                        }
                        Action {
                            objectName: "followSave"; Layout.fillWidth: true; quiet: true
                            visible: fieldGuide.marker >= 0
                            text: viewer.savedPlace >= 0 ? "Follow my save" : "Clear marked place"
                            onClicked: {
                                fieldGuide.clearMarker()
                                if (fieldGuide.marker < 0 && viewer.savedPlace >= 0) viewer.setPage(viewer.route[viewer.savedPlace].id)
                            }
                        }
                    }
                }

                ColumnLayout {
                    visible: viewer.page === "genes"
                    Layout.fillWidth: true
                    spacing: 11
                    GridLayout {
                        Layout.fillWidth: true; columns: viewer.narrow ? 1 : 2
                        rowSpacing: 11; columnSpacing: 22
                        ColumnLayout {
                            Layout.row: 0; Layout.column: 0; Layout.preferredWidth: 570; Layout.fillWidth: true; Layout.alignment: Qt.AlignTop
                            Title { Layout.fillWidth: true; text: "Build a recipe" }
                            Copy { Layout.fillWidth: true; text: "Choose up to three genes. Select one again to remove it." }
                            GridLayout {
                                Layout.fillWidth: true; columns: viewer.narrow ? 1 : 3; columnSpacing: 10; rowSpacing: 8
                                Repeater {
                                    model: Book.specimens
                                    delegate: Action {
                                        required property int index
                                        required property var modelData
                                        objectName: "gene" + index
                                        Layout.fillWidth: true; Layout.preferredWidth: 170
                                        selected: viewer.chosen.indexOf(index) >= 0
                                        Accessible.checkable: true; Accessible.checked: selected
                                        largePlate: !viewer.narrow
                                        text: (selected ? "✓  " : "") + modelData.name
                                        detail: modelData.ap + " AP"
                                        art: fieldGuide.plate(modelData.id)
                                        onClicked: viewer.chooseGene(index)
                                    }
                                }
                            }
                        }
                        Action {
                            id: allGeneAction
                            Layout.row: viewer.narrow ? 2 : 1; Layout.column: 0
                            objectName: "revealGenes"; visible: viewer.allGenes.length > 3
                            text: viewer.revealNames ? "Hide later gene names" : "Show all " + viewer.allGenes.length + " genes (spoilers)"
                            quiet: true; onClicked: viewer.revealNames = !viewer.revealNames
                        }
                        GridLayout {
                            visible: viewer.revealNames && viewer.allGenes.length > 3
                            Layout.row: viewer.narrow ? 3 : 2; Layout.column: 0
                            Layout.fillWidth: true; columns: viewer.narrow ? 2 : 3; columnSpacing: 9; rowSpacing: 8
                            Repeater {
                                model: viewer.revealNames ? viewer.allGenes.slice(3) : []
                                delegate: Action {
                                    required property int index
                                    required property var modelData
                                    objectName: "gene" + (index+3)
                                    Layout.fillWidth: true; Layout.preferredWidth: 100
                                    selected: viewer.chosen.indexOf(index+3) >= 0
                                    Accessible.checkable: true; Accessible.checked: selected
                                    text: (selected ? "✓  " : "") + modelData.name
                                    detail: modelData.ap + " AP"
                                    art: fieldGuide.plate(modelData.art)
                                    onClicked: viewer.chooseGene(index+3)
                                }
                            }
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; visible: viewer.chosen.includes(16)
                        Title { text: "Who is standing with Ryu?" }
                        Flow {
                            Layout.fillWidth: true; spacing: 6
                            Repeater {
                                model: ["Nina","Garr","Rei","Momo","Peco"]
                                delegate: Action {
                                    required property string modelData
                                    objectName: "ally" + modelData
                                    text: (selected ? "✓  " : "") + modelData
                                    selected: viewer.partyAllies.includes(modelData)
                                    Accessible.checkable: true; Accessible.checked: selected
                                    onClicked: {
                                        const next = viewer.partyAllies.filter(a => a !== modelData)
                                        if (!selected && next.length === 2) { viewer.notice = "Remove one ally first."; return }
                                        viewer.partyAllies = selected ? next : next.concat([modelData])
                                        viewer.partyKnown = true; viewer.notice = ""
                                    }
                                }
                            }
                            Action { text: "Ryu alone"; selected: viewer.partyKnown && !viewer.partyAllies.length
                                onClicked: { viewer.partyAllies = []; viewer.partyKnown = true; viewer.notice = "" } }
                        }
                    }
                    Title { text: "Specimen notes" }
                    GridLayout {
                        Layout.fillWidth: true; columns: viewer.narrow ? 1 : 3
                        Repeater {
                            model: Book.specimens
                            delegate: Action {
                                required property var modelData
                                Layout.fillWidth: true; Layout.preferredWidth: 90
                                objectName: "read" + modelData.id
                                text: modelData.name; quiet: true; onClicked: viewer.visit(modelData.id)
                            }
                        }
                    }
                }

                ColumnLayout {
                    visible: viewer.page === "masters"
                    Layout.fillWidth: true
                    spacing: 11
                    Title { Layout.fillWidth: true; text: "Compare two masters" }
                    Copy { Layout.fillWidth: true; text: "See how a change of master affects the next level." }
                    GridLayout {
                        Layout.fillWidth: true; columns: viewer.narrow ? 1 : 2; columnSpacing: 12; rowSpacing: 8
                        Action {
                            objectName: "masterSlotA"; Layout.fillWidth: true; Layout.preferredWidth: 100
                            text: viewer.allMasters[viewer.first].name; detail: "Current master"; selected: viewer.picker === "A"
                            Accessible.name: "Current master, " + text
                            onClicked: viewer.chooseMaster("A")
                        }
                        Action {
                            objectName: "masterSlotB"; Layout.fillWidth: true; Layout.preferredWidth: 100
                            text: viewer.allMasters[viewer.second].name; detail: "Compare with"; selected: viewer.picker === "B"
                            Accessible.name: "Compare with " + text
                            onClicked: viewer.chooseMaster("B")
                        }
                    }
                    Action {
                        objectName: "revealMasters"; visible: viewer.allMasters.length > 2
                        text: viewer.revealNames ? "Hide later master names" : "Show all " + viewer.allMasters.length + " entries (spoilers)"
                        quiet: true
                        onClicked: {
                            viewer.revealNames = !viewer.revealNames
                            if (!viewer.revealNames) {
                                viewer.first = viewer.first > 1 ? 0 : viewer.first
                                viewer.second = viewer.second > 1 ? 1 : viewer.second
                            }
                        }
                    }
                    GridLayout {
                        visible: !!viewer.picker; Layout.fillWidth: true; columns: viewer.narrow ? 1 : 3
                        Repeater {
                            model: viewer.picker ? viewer.allMasters.slice(0, viewer.revealNames ? viewer.allMasters.length : 2) : []
                            delegate: Action {
                                required property int index
                                required property var modelData
                                objectName: "masterChoice"+index; Layout.fillWidth: true; Layout.preferredWidth: 130
                                text: modelData.name
                                selected: (viewer.picker === "A" ? viewer.first : viewer.second) === index
                                onClicked: {
                                    const slot = viewer.picker
                                    if (slot === "A") viewer.first = index
                                    else viewer.second = index
                                    viewer.picker = ""
                                    viewer.focusNamed("masterSlot"+slot)
                                }
                            }
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 0
                        Repeater {
                            model: 7
                            delegate: Rectangle {
                                id: ledgerRow
                                required property int index
                                readonly property int leftValue: index ? viewer.allMasters[viewer.first].stats[index-1] : 0
                                readonly property int rightValue: index ? viewer.allMasters[viewer.second].stats[index-1] : 0
                                Layout.fillWidth: true
                                implicitHeight: Math.max(viewer.tv ? 49 : 36, columns.implicitHeight + 10)
                                color: index === 0 ? viewer.pale : index % 2 === 1 ? "#fffdf6" : viewer.paper
                                RowLayout {
                                    id: columns
                                    anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10
                                    Repeater {
                                        model: ledgerRow.index ? [
                                            Book.statNames[ledgerRow.index-1], viewer.signed(ledgerRow.leftValue),
                                            viewer.signed(ledgerRow.rightValue), viewer.signed(ledgerRow.rightValue-ledgerRow.leftValue)
                                        ] : ["Per level", viewer.allMasters[viewer.first].name, viewer.allMasters[viewer.second].name, "Change"]
                                        delegate: Copy {
                                            required property int index
                                            required property string modelData
                                            Layout.fillWidth: true; Layout.preferredWidth: index===0 ? 120 : 100
                                            text: modelData; color: index===3 ? viewer.accent : viewer.ink
                                            font.pixelSize: viewer.tv ? 20 : 15
                                            font.weight: ledgerRow.index===0 || index===3 ? Font.DemiBold : Font.Normal
                                            horizontalAlignment: index ? Text.AlignHCenter : Text.AlignLeft
                                        }
                                    }
                                }
                            }
                        }
                    }
                    Copy {
                        objectName: "masterSummary"
                        Layout.fillWidth: true
                        text: {
                            const changes = Book.statNames.map((s,i) => {
                                const d=viewer.allMasters[viewer.second].stats[i]-viewer.allMasters[viewer.first].stats[i]
                                return d ? s + " " + viewer.signed(d) : ""
                            }).filter(Boolean)
                            return changes.length ? "Per level: " + changes.join(", ") + "." : "The six modifiers are identical."
                        }
                    }
                    Action { text: "Read about Rwolf"; quiet: true; onClicked: viewer.visit("rwolf") }
                }

                ColumnLayout {
                    visible: viewer.page === viewer.volume.article.id
                    Layout.fillWidth: true
                    Copy { text: viewer.volume.article.intro; Layout.fillWidth: true }
                    Repeater {
                        model: viewer.volume.article.sections
                        delegate: ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true; spacing: 5
                            Title { Layout.fillWidth: true; text: modelData[0] }
                            Copy { Layout.fillWidth: true; text: modelData[1] }
                        }
                    }
                    Action { text: viewer.third ? "Open walkthrough" : "Compare master growth"; quiet: true; onClicked: viewer.visit(viewer.third ? "walk" : "masters") }
                }
                ColumnLayout {
                    readonly property int specimen: Book.specimens.findIndex(s => s.id === viewer.page)
                    id: leaf
                    visible: specimen >= 0 || viewer.page === "rwolf"
                    Layout.fillWidth: true
                    GridLayout {
                        Layout.fillWidth: true; columns: viewer.narrow ? 1 : 2; columnSpacing: 20
                        Image {
                            visible: leaf.specimen >= 0
                            Layout.preferredWidth: viewer.narrow ? 210 : 250; Layout.preferredHeight: 155
                            source: leaf.specimen >= 0 ? fieldGuide.plate(viewer.page) : ""
                            fillMode: Image.PreserveAspectFit
                            Accessible.role: Accessible.Graphic
                            Accessible.name: leaf.specimen >= 0 ? Book.specimens[leaf.specimen].shape : ""
                        }
                        Copy {
                            Layout.fillWidth: true
                            text: leaf.specimen >= 0 ? Book.specimens[leaf.specimen].name + " is an elemental gene. Add it to a recipe for 5 initial AP."
                                 : "Under Rwolf, each level gains 1 extra AP and 1 extra Wisdom. Power gains 1 less than it would without a master."
                        }
                    }
                    Action {
                        text: leaf.specimen >= 0 ? "Try in the gene builder" : "Open master comparison"
                        onClicked: {
                            if (leaf.specimen >= 0) { viewer.chosen = [leaf.specimen]; viewer.visit("genes") }
                            else { viewer.first=0; viewer.second=1; viewer.visit("masters") }
                        }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 10; visible: viewer.page === "route"
                    Copy { Layout.fillWidth: true; color: viewer.muted; text: "Choose a stop. Your marked place stays where you left it." }
                    Repeater {
                        model: viewer.page === "route" ? viewer.route.filter(r => viewer.isAvailable(r.id)) : []
                        delegate: Action {
                            required property int index
                            required property var modelData
                            objectName: "stop" + modelData.id
                            Layout.fillWidth: true; text: (index+1) + ".  " + modelData.title
                            detail: modelData.region; selected: index === viewer.currentPlace
                            onClicked: viewer.visit(modelData.id)
                        }
                    }
                    SpoilerSwitch { objectName: "routeSpoilers" }
                }
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 12; visible: viewer.page === "wiki"
                    Title { Layout.fillWidth: true; text: viewer.category || "Browse by subject" }
                    Action {
                        objectName: "allSubjects"; visible: !!viewer.category
                        text: "‹  All subjects"; quiet: true
                        onClicked: { viewer.category = ""; viewer.focusNamed("category0") }
                    }
                    GridLayout {
                        Layout.fillWidth: true; columns: viewer.narrow ? 1 : 2
                        rowSpacing: 8; columnSpacing: 14
                        Repeater {
                            model: viewer.page === "wiki" && !viewer.category ?
                                Array.from(new Set(viewer.articles.map(a => a.category))) : []
                            delegate: Action {
                                required property int index
                                required property string modelData
                                objectName: "category" + index
                                Layout.fillWidth: true; Layout.preferredWidth: 200
                                text: modelData
                                detail: viewer.subjectDetail(modelData)
                                art: fieldGuide.plate(viewer.articles.find(a => a.category === modelData).art)
                                onClicked: viewer.openSubject(modelData)
                            }
                        }
                        Repeater {
                            model: viewer.page === "wiki" && viewer.category ? viewer.wikiRows() : []
                            delegate: Action {
                                required property var modelData
                                Layout.fillWidth: true; Layout.preferredWidth: 200
                                objectName: "wiki" + modelData.id; text: modelData.title
                                detail: modelData.lead
                                onClicked: viewer.visit(modelData.id)
                            }
                        }
                    }
                    Action {
                        objectName: "revealSubject"
                        readonly property int later: viewer.articles.filter(a => a.category === viewer.category && !viewer.isAvailable(a.id)).length
                        visible: !!viewer.category && later > 0
                        text: "Show " + later + (later === 1 ? " later article" : " later articles") + " (spoilers)"
                        onClicked: { viewer.revealedSubjects = viewer.revealedSubjects.concat([viewer.category]); viewer.focusNamed("wiki" + viewer.wikiRows()[0].id) }
                    }
                    SpoilerSwitch { objectName: "wikiSpoilers"; visible: !viewer.category }
                }
                ColumnLayout {
                    visible: !!viewer.article; Layout.fillWidth: true; spacing: 13
                    Copy {
                        Layout.fillWidth: true; Layout.maximumWidth: 810
                        visible: !!viewer.article && !viewer.article.table
                        text: viewer.article ? viewer.article.lead : ""; font.pixelSize: viewer.bodySize+2
                    }
                    FieldLedger {
                        Layout.fillWidth: true; visible: !!(viewer.article && viewer.article.table)
                        records: viewer.article ? viewer.article.records || [] : []
                        monsters: !!viewer.article && viewer.article.table === "encounters"
                        accent: viewer.accent; tv: viewer.tv
                    }
                    Repeater {
                        model: viewer.article ? viewer.article.sections : []
                        delegate: GridLayout {
                            required property var modelData
                            Layout.fillWidth: true; columns: viewer.narrow ? 1 : 2
                            rowSpacing: 8; columnSpacing: 22
                            Rule { Layout.columnSpan: viewer.narrow ? 1 : 2 }
                            Title {
                                Layout.fillWidth: true; Layout.preferredWidth: 285; Layout.alignment: Qt.AlignTop
                                text: modelData.title
                            }
                            Copy {
                                Layout.fillWidth: true; Layout.preferredWidth: 630; Layout.alignment: Qt.AlignTop
                                text: modelData.text
                            }
                        }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    readonly property var related: viewer.subject ? viewer.subject.links.filter(id => viewer.isAvailable(id)) : []
                    id: references
                    visible: !!viewer.subject
                    Rule { }
                    Kicker { visible: references.related.length > 0; text: "RELATED PAGES" }
                    GridLayout {
                        Layout.fillWidth: true; columns: viewer.narrow ? 1 : 2
                        Repeater {
                            model: references.related
                            delegate: Action {
                                required property string modelData
                                objectName: "related" + modelData
                                Layout.fillWidth: true; Layout.preferredWidth: 160
                                quiet: true; text: viewer.titleOf(modelData) + "  ›"
                                onClicked: viewer.visit(modelData)
                            }
                        }
                    }
                    Action {
                        objectName: "guideSources"
                        visible: !!viewer.subject && viewer.subject.sources.length > 0
                        text: viewer.sourcesOpen ? "Hide sources" : "Sources"; quiet: true
                        onClicked: viewer.sourcesOpen = !viewer.sourcesOpen
                    }
                    Repeater {
                        model: viewer.subject && viewer.sourcesOpen ? viewer.subject.sources : []
                        delegate: ColumnLayout {
                            id: sourceRow
                            required property string modelData
                            Layout.fillWidth: true
                            readonly property var citation: viewer.book.sources[modelData]
                            Copy { Layout.fillWidth: true; visible: !sourceRow.citation.url; text: sourceRow.citation.title }
                            Action {
                                Layout.fillWidth: true; quiet: true; visible: !!sourceRow.citation.url
                                text: sourceRow.citation.title; detail: "Open source in browser"
                                onClicked: Qt.openUrlExternally(sourceRow.citation.url)
                            }
                        }
                    }
                }
                Rule { visible: viewer.page !== "guide" }
                Action {
                    id: pinAction
                    objectName: "pinEntry"; visible: !["guide","wiki","route"].includes(viewer.page)
                    text: fieldGuide.pins.indexOf(viewer.pinId) >= 0 ? "Remove pin" : "Pin this page"
                    quiet: true
                    onClicked: fieldGuide.togglePin(viewer.pinId)
                }
                Copy {
                    visible: !!text; Layout.fillWidth: true
                    text: fieldGuide.message || (viewer.page === "genes" ? "" : viewer.notice)
                    Accessible.role: Accessible.AlertMessage
                }
            }
        }
        Rectangle {
            Layout.fillWidth: true; visible: viewer.page === "genes"
            implicitHeight: resultRow.implicitHeight + 18
            color: "#e3ebdf"
            Rectangle { width: parent.width; height: 2; color: viewer.accent }
            RowLayout {
                id: resultRow
                anchors.left: parent.left; anchors.right: parent.right
                anchors.leftMargin: viewer.narrow ? 15 : 30; anchors.rightMargin: anchors.leftMargin
                anchors.verticalCenter: parent.verticalCenter; spacing: 14
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 2
                    Kicker {
                        visible: viewer.chosen.length > 0; Layout.fillWidth: true
                        text: viewer.chosen.map(i => (viewer.allGenes[i] || {}).name || "").join("  +  ")
                    }
                    Title { objectName: "geneForm"; Layout.fillWidth: true
                        text: viewer.result.form || (viewer.chosen.length ? "Recipe unavailable" : "Choose your first gene") }
                    Copy { Layout.fillWidth: true; font.pixelSize: viewer.tv ? 20 : 15
                        text: viewer.notice || viewer.result.detail || "Select up to three specimens to preview Ryu’s form." }
                }
                ColumnLayout {
                    spacing: 2
                    Kicker { objectName: "geneResult"; text: viewer.result.cost !== undefined ? viewer.result.cost + " initial AP" : "" }
                    Action { id: clearGeneButton; objectName: "clearRecipe"; visible: viewer.chosen.length > 0
                        text: "Clear recipe"; quiet: true
                        onClicked: { viewer.chosen = []; viewer.notice = ""; viewer.focusNamed("gene0") } }
                }
            }
        }
    }
}
