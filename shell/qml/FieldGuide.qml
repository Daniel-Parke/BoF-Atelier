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
    enum InitialReading { AwaitingSave, ReadingByChoice, SaveRecognised }
    property int initialReading: FieldGuide.AwaitingSave
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
    readonly property var sheets: book.fieldSheets || ({})
    readonly property var entities: book.entities || ({})
    readonly property var stop: route[Math.min(place, route.length - 1)] || ({})
    readonly property var article: articles.find(e => e.id === page) || null
    readonly property var entity: entities[page] || null
    readonly property var sheet: page === "walk" ? Object.values(sheets).find(s => s.stop === stop.id && (!area || s.area === area.name)) || null : null
    readonly property var subject: page === "walk" ? stop : article
    readonly property string pageArt: sheet ? sheet.art : subject ? subject.art : page === "masters" ? "iv-training" : volume.theme
    readonly property bool specimenArt: pageArt.startsWith("gene-") || ["flame","frost","thunder","iv-fishing","iv-training","iv-dragon"].includes(pageArt)
    readonly property string pinId: page === "walk" ? stop.id : page
    readonly property string bookmarkId: sheet ? sheet.id : pinId
    readonly property int savedPlace: gameStory && gameStory.game === game ? route.findIndex(p => p.id === gameStory.place) : -1
    readonly property int currentPlace: fieldGuide.marker >= 0 ? fieldGuide.marker : savedPlace
    readonly property int savedFloor: page === "walk" && place === savedPlace && fieldGuide.marker < 0
                                      && gameStory.floorId !== undefined ? gameStory.floorId : -1
    property string chosenArea: ""
    readonly property var areas: stop.sectionsByArea || []
    readonly property var savedArea: areas.find(s => s.floorIds.includes(savedFloor)) || null
    readonly property var area: areas.find(s => s.name === chosenArea) || savedArea || areas[0] || null
    readonly property int firstStep: area ? area.firstStep : 0
    readonly property var visibleFloors: area ? (stop.floors || []).filter(f => area.floorIds.includes(f.mapId)) : stop.floors || []
    readonly property bool hasWarning: !!stop.warning && (!area || !!area.warning)
    readonly property bool schematicAvailable: !!stop.map && (!area || area.name === areas[0].name)
    readonly property int readableThrough: Math.max(0, currentPlace, visitedThrough)
    property int visitedThrough: 0
    property bool showLater: false
    property bool sourcesOpen: false
    property string category: ""
    property var revealedSubjects: []
    readonly property color accent: third ? "#215a4a" : "#853a29"
    readonly property color paper: third ? "#f3f1e3" : "#f6f1e5"
    readonly property color pale: third ? "#e0e6d2" : "#eadfc9"
    readonly property color ink: third ? "#203436" : "#332b25"
    readonly property color muted: third ? "#4b5a54" : "#61584d"
    readonly property color binding: third ? "#162f38" : "#302828"
    readonly property string displayFace: Qt.fontFamilies().includes("Gloock") ? "Gloock" : "Georgia"
    readonly property bool railVisible: width >= (tv ? 1360 : 1020)
    readonly property real railWidth: railVisible ? (tv ? 228 : 190) : 0
    readonly property int bodySize: tv ? 23 : 17
    readonly property bool narrow: width < (tv ? 870 : 695)
    readonly property var roster: fieldGuide.catalog
    readonly property var allGenes: roster.genes || Book.specimens
    readonly property var allMasters: {
        const disc = roster.masters || []
        const teachers = book.game === "bof4" ? (book.teachers || []).filter(t => t.growth) : []
        if (!teachers.length) return disc.length ? disc : Book.masterExamples
        const keys = ["HP","AP","power","defence","agility","wisdom"]
        const rows = [disc[0] || Book.masterExamples[0]]
        for (const teacher of teachers) {
            const verified = disc.find(row => row.name === teacher.name)
            rows.push(verified || {name: teacher.name, stats: keys.map(key => teacher.growth[key])})
        }
        return rows.concat(disc.filter(row => rows.every(reference => reference.name !== row.name)))
    }
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
    property int selectedStep: 1
    property bool readingFloor: false
    property bool afterOpen: false
    property bool enginesOpen: false
    property string atlasSection: ""
    property bool loreOpen: false
    readonly property string activeSection: atlasSection || (stop.map || stop.floors ? "Map" : "Notes")
    property bool overview: false
    property bool mapExpanded: false
    property bool routeExpanded: false
    property bool revealNames: false
    property int first: 0
    property int second: 1
    property string picker: ""
    property string notice: ""
    property string query: ""
    function openSearch() {
        if (page !== "guide") visit("guide")
        focusNamed("guideSearch")
    }
    function chooseArea(name) {
        chosenArea = name
        hintOpen = false; stepOpen = false; loreOpen = false; overview = false; afterOpen = false
        readingFloor = false; mapExpanded = false; routeExpanded = false; enginesOpen = false; atlasSection = ""
        selectedStep = sheet && sheet.id === "kurok" ? 2 : 1
        rememberReadingChoice()
    }
    function entityId(row, monsters) {
        return (monsters ? "enemy." : "item.") + row.name.trim().toLowerCase()
    }
    function observationTargets(row) {
        return row.areaIds?.length ? row.areaIds : [row.stop]
    }

    function rememberReadingChoice() {
        if (!inSession || initialReading === FieldGuide.SaveRecognised) return
        initialReading = FieldGuide.ReadingByChoice
        if (page === "walk" && area && !chosenArea) chosenArea = area.name
    }
    function openBook(id, revision, branch, initial) {
        const scope = JSON.stringify([id,revision,branch])
        const sameSession = inSession && sessionContext === scope
        if (!sameSession) initialReading = FieldGuide.AwaitingSave
        const saved = gameStory && gameStory.game === id && gameStory.place ?
                      JSON.stringify([gameStory.place, gameStory.floorId, gameStory.visitKey || ""]) : ""
        // A delayed first observation establishes the baseline for the next visit.
        const keepReading = sameSession && (!initial || initial === "guide") &&
                (fieldGuide.marker >= 0 || lastSavedPlace === saved || (saved && initialReading === FieldGuide.ReadingByChoice))
        if (saved) initialReading = FieldGuide.SaveRecognised
        lastSavedPlace = saved
        if (keepReading) {
            Qt.callLater(function() { if (viewer.visible) landing.forceActiveFocus() })
            return
        }
        sessionContext = inSession ? scope : ""
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
        if (!book.route) {
            setPage("guide")
            return
        }
        const start = known(initial) ? initial : "guide"
        const followPlace = (start === "guide" || start === "walk") && currentPlace >= 0
        setPage(followPlace ? (fieldGuide.markTarget || route[currentPlace].id) : start, followPlace && fieldGuide.marker < 0)
        if (start !== "guide") rememberReadingChoice()
    }
    function known(id) {
        return ["guide","wiki","route","bookmarks"].includes(id) || !!sheets[id] || !!entities[id] || volume.entries.concat(leaves, articles, route).some(entry => entry.id === id)
    }
    function titleOf(id) {
        if (id === "wiki") return "Field wiki"
        if (id === "route") return "Walkthrough"
        if (id === "bookmarks") return "Bookmarks"
        if (sheets[id]) return sheets[id].title
        if (entities[id]) return entities[id].name
        const found = volume.entries.concat(leaves, articles, route).find(entry => entry.id === id)
        return found ? found.title : "Field guide"
    }
    function setPage(id, followSave = false) {
        const targetSheet = sheets[id]
        const targetId = targetSheet ? targetSheet.stop : id
        const index = route.findIndex(p => p.id === targetId)
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
        routeExpanded = false
        chosenArea = targetSheet && !followSave ? targetSheet.area : ""
        selectedStep = sheet && sheet.id === "kurok" ? 2 : 1
        readingFloor = false
        afterOpen = false
        enginesOpen = false
        loreOpen = false
        sourcesOpen = false
        scroller.contentY = 0
        Qt.callLater(function() {
            if (!viewer.visible) return
            landing.forceActiveFocus()
        })
    }
    function visit(id) {
        if (!known(id) || page === id || (page === "walk" && id === bookmarkId)) return
        const focused = controls().find(item => item.activeFocus)
        history = history.concat([{id: page === "walk" ? bookmarkId : page, chosenArea: chosenArea,
                    step: selectedStep, expandedSteps: stepOpen, section: atlasSection, hint: hintOpen, lore: loreOpen,
                    floor: readingFloor, floorIndex: floorSheet.index, floorPin: floorSheet.pin,
                    overview: overview, enlarged: mapExpanded, enlargedRoute: routeExpanded, after: afterOpen, engines: enginesOpen,
                    category: category, y: scroller.contentY, focus: focused ? focused.objectName : ""}])
        if (id === "walk") place = Math.max(0, currentPlace)
        setPage(id)
        rememberReadingChoice()
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
            setPage(destination.id)
            chosenArea = destination.chosenArea
            selectedStep = destination.step; stepOpen = destination.expandedSteps
            atlasSection = destination.section; hintOpen = destination.hint; loreOpen = destination.lore
            readingFloor = destination.floor; overview = destination.overview; mapExpanded = destination.enlarged
            routeExpanded = destination.enlargedRoute
            afterOpen = destination.after; enginesOpen = destination.engines; category = destination.category
            Qt.callLater(function() {
                floorSheet.index = Math.max(0, Math.min(destination.floorIndex, visibleFloors.length - 1))
                floorSheet.pin = destination.floorPin
                scroller.contentY = Math.min(destination.y, Math.max(0,scroller.contentHeight-scroller.height))
                const target = controls().find(item => item.objectName && item.objectName === destination.focus)
                if (target) target.forceActiveFocus()
            })
        } else {
            exitRequested()
        }
    }
    function isAvailable(id) {
        if (showLater) return true
        if (entities[id]) return revealedSubjects.includes(entities[id].category) || isAvailable(entities[id].unlock)
        if (sheets[id] && sheets[id].stop !== id) return isAvailable(sheets[id].stop)
        const r = route.findIndex(p => p.id === id)
        if (r >= 0) return r <= readableThrough
        const a = articles.find(e => e.id === id)
        return !a || revealedSubjects.includes(a.category) || route.findIndex(p => p.id === a.unlock) <= readableThrough
    }
    function wikiRows() {
        const records = articles.filter(a => isAvailable(a.id) && (!category || a.category === category))
        if (category !== "Item ledger" && category !== "Bestiary") return records
        const names = Object.values(entities).filter(e => e.category === category && (isAvailable(e.id) || revealedSubjects.includes(category)))
            .map(e => ({id: e.id, title: e.name, lead: e.observations[0].where}))
            .sort((a,b) => a.title.localeCompare(b.title))
        return names.concat(records)
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
        const term = Book.searchText(query)
        const words = term.split(" ").filter(Boolean)
        const index = volume.entries.map(e => e.id === "walk" ? Object.assign({}, e, {detail: route.length + " stops · Hints and directions", art: route[0].art}) : e)
        if (articles.length) index.splice(1,0,{id:"wiki",title:"Field wiki",detail:articles.length + " articles · Browse by subject",terms:"encyclopaedia wiki reference",art:third ? "iii-woods" : "iv-river"})
        if (!words.length) return index
        const named = Object.values(entities).filter(e => isAvailable(e.id)).map(e => ({
            id:e.id, title:e.name, detail:e.observations[0].where,
            terms:e.observations.filter(o => isAvailable(o.stop)).map(o => o.where + " " + o.detail).join(" ")
        }))
        const illustrated = Object.values(sheets).filter(s => isAvailable(s.id)).map(s => ({
            id:s.id, title:s.title, detail:s.chapter, aliases:[s.area].concat(s.aliases || []), terms:[s.area,s.mapTitle,s.objective,s.mapAlt]
                .concat(s.steps.map(step => step.title + " " + step.body)).join(" ")
        }))
        const records = index.concat(leaves, illustrated, named, route.filter(e => isAvailable(e.id) && !sheets[e.id]).map(e => ({
            id:e.id,title:e.title,detail:e.region,aliases:e.aliases || [],terms:e.lead + " " + (e.landmarks || []).concat(e.steps || []).join(" ")
        })), articles.filter(e => isAvailable(e.id)).map(e => ({
            id:e.id,title:e.title,detail:e.category,aliases:e.aliases || [],terms:e.lead + " " + (e.sections || []).map(s => s.title + " " + s.text).join(" ")
                + " " + (e.records || []).map(r => r.name + " " + r.where + " " + r.detail).join(" ")
                + " " + (e.referenceTables || []).map(t => t.rows.map(cells => cells.join(" ")).join(" ")).join(" ")
        })))
        return records.filter(entry => {
            const haystack = Book.searchText([entry.title, entry.detail, entry.terms].concat(entry.aliases || []).join(" "))
            return words.every(word => haystack.indexOf(word) >= 0)
        }).sort((a,b) => Book.searchRank(term, a.title, a.aliases) - Book.searchRank(term, b.title, b.aliases))
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
        if (item.mapToItem(scroller.contentItem, 0, 0).y < 0 || item.fixedAction || item === returnAction || item === indexAction || item === clearGeneButton) return
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
        if (!item || item.fixedAction || item === indexAction || item === returnAction || item === clearGeneButton || (action !== "down" && action !== "up")) return false
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
            if ((item.fixedAction || item === indexAction || item === returnAction) && !active.fixedAction && active !== indexAction && active !== returnAction &&
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
               page === "masters" ? "masterSlotA" : page === "walk" ? (sheet ? "routeDirection"+selectedStep : "guideHint") :
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
        lineHeight: 1.18
        Accessible.role: Accessible.StaticText; Accessible.name: text
    }
    component Title: Copy {
        font.family: viewer.displayFace; font.pixelSize: viewer.tv ? 34 : 27
        color: viewer.ink
        Accessible.role: Accessible.Heading
    }
    component Kicker: Copy {
        color: viewer.accent; font.family: "Barlow Semi Condensed"; font.pixelSize: viewer.tv ? 20 : 16
        font.weight: Font.DemiBold; font.letterSpacing: 0.45
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
    Rectangle {
        id: rail
        visible: viewer.railVisible; width: viewer.railWidth
        anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom
        color: viewer.binding
        Rectangle { width: 2; height: parent.height; anchors.right: parent.right; color: "#9d8560" }
        ColumnLayout {
            anchors.left: parent.left; anchors.right: parent.right
            spacing: 5
            Rectangle {
                Layout.fillWidth: true; Layout.rightMargin: 2
                implicitHeight: 147; color: viewer.binding; clip: true
                Image { anchors.fill: parent; source: fieldGuide.plate(viewer.volume.theme); fillMode: Image.PreserveAspectCrop; opacity: .45; Accessible.ignored: true }
                ColumnLayout {
                    anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 17; spacing: 3
                    Kicker { color: "#f2dcac"; text: "Field Guide" }
                    Title { text: viewer.volume.title; Layout.fillWidth: true; color: "#fff5da"; font.pixelSize: viewer.tv ? 34 : 29 }
                }
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 2; color: "#bb9b6e" }
            }
            Repeater {
                model: [{id:"route",label:"Walkthrough"}, {id:"wiki",label:"Field wiki"},
                        {id:viewer.third ? "genes" : "masters",label:viewer.third ? "Dragon genes" : "Master training"},
                        {id:"bookmarks",label:"Bookmarks"}]
                delegate: Action {
                    required property var modelData
                    readonly property bool fixedAction: true
                    objectName: "spine" + modelData.id
                    Layout.fillWidth: true; Layout.leftMargin: 10; Layout.rightMargin: 12
                    Layout.topMargin: modelData.id === "route" ? 8 : 0
                    text: modelData.label; dark: true; quiet: true
                    selected: viewer.page === modelData.id || (viewer.page === "walk" && modelData.id === "route")
                    onClicked: viewer.visit(modelData.id)
                }
            }
            ColumnLayout {
                id: nearby
                Layout.fillWidth: true; Layout.leftMargin: 10; Layout.rightMargin: 12; Layout.topMargin: 10
                visible: viewer.height >= (viewer.tv ? 770 : 645)
                readonly property var stops: viewer.route.slice(Math.max(0, viewer.place-1), viewer.place+2)
                    .filter(r => viewer.isAvailable(r.id))
                spacing: 3
                Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#827963" }
                Kicker { Layout.fillWidth: true; Layout.topMargin: 8; text: viewer.stop.region || "Walkthrough"; color: "#ecd198" }
                Repeater {
                    model: nearby.stops
                    delegate: Action {
                        required property var modelData
                        readonly property bool fixedAction: true
                        Layout.fillWidth: true; dark: true; quiet: true
                        text: viewer.sheet && viewer.stop.id === modelData.id ? viewer.sheet.title : viewer.titleOf(modelData.id)
                        selected: viewer.page === "walk" && viewer.stop.id === modelData.id
                        onClicked: if (!selected) viewer.visit(modelData.id)
                    }
                }
            }
        }
    }
    ColumnLayout {
        anchors.fill: parent; anchors.leftMargin: viewer.railWidth
        spacing: 0
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: topBar.implicitHeight + (viewer.tv ? 20 : 12)
            color: viewer.paper
            RowLayout {
                id: topBar
                anchors.fill: parent; anchors.leftMargin: viewer.narrow ? 16 : 32; anchors.rightMargin: anchors.leftMargin
                spacing: viewer.narrow ? 5 : 10
                Action {
                    readonly property bool fixedAction: true
                    visible: viewer.history.length > 0; text: "Back"; quiet: true
                    objectName: "readerBack"; onClicked: viewer.goBack()
                }
                Action {
                    id: indexAction
                    objectName: "guideIndex"
                    text: "Contents"
                    quiet: true
                    enabled: viewer.page !== "guide"
                    onClicked: viewer.visit("guide")
                }
                Item { Layout.fillWidth: true }
                Action {
                    readonly property bool fixedAction: true
                    objectName: "guideFind"; visible: viewer.page !== "guide"; text: "Search"; quiet: true
                    onClicked: viewer.openSearch()
                }
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
            contentWidth: width; contentHeight: column.implicitHeight + 35
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { }
            ColumnLayout {
                id: column
                width: Math.min(scroller.width - (viewer.narrow ? 30 : 48), viewer.tv ? 1400 : 1260)
                x: (scroller.width-width)/2
                spacing: viewer.tv ? 19 : 13
                Rectangle {
                    id: hero
                    readonly property bool cabinet: viewer.page === "genes"
                    Layout.fillWidth: true
                    Layout.leftMargin: -column.x; Layout.rightMargin: -column.x
                    implicitHeight: Math.max(heroWords.implicitHeight + (viewer.narrow ? 28 : 36),
                        cabinet ? (viewer.narrow ? 97 : 117) : viewer.narrow ? 154 : 172)
                    color: cabinet ? "#173845" : viewer.paper; clip: true
                    Image {
                        id: panorama; objectName: "guidePanorama"
                        anchors.fill: parent
                        source: fieldGuide.plate(viewer.pageArt) || fieldGuide.plate(viewer.volume.theme)
                        fillMode: viewer.specimenArt ? Image.PreserveAspectFit : Image.PreserveAspectCrop
                        horizontalAlignment: Image.AlignRight
                        verticalAlignment: viewer.subject ? Image.AlignVCenter : Image.AlignTop
                        opacity: hero.cabinet ? .2 : 1
                        smooth: true; mipmap: true; Accessible.ignored: true
                    }
                    Rectangle {
                        id: heroWash
                        anchors.fill: parent
                        readonly property color wash: hero.cabinet ? "#163642" : viewer.paper
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0; color: heroWash.wash }
                            GradientStop { position: .34; color: heroWash.wash }
                            GradientStop { position: .68; color: Qt.rgba(heroWash.wash.r,heroWash.wash.g,heroWash.wash.b,.75) }
                            GradientStop { position: 1; color: Qt.rgba(heroWash.wash.r,heroWash.wash.g,heroWash.wash.b,0) }
                        }
                    }
                    ColumnLayout {
                        id: heroWords; x: Math.max(column.x,16); anchors.verticalCenter: parent.verticalCenter
                        width: Math.min(parent.width - x*2, Math.max(parent.width*(viewer.narrow ? .76 : .67),235))
                        spacing: viewer.narrow ? 3 : 5
                        Kicker {
                            Layout.fillWidth: true
                            color: hero.cabinet ? "#f2cb8c" : viewer.accent
                            text: viewer.sheet ? viewer.sheet.chapter : viewer.article ? viewer.article.category :
                                  viewer.entity ? viewer.entity.category : viewer.page === "walk" ? viewer.stop.region : viewer.volume.title
                        }
                        Title {
                            id: landing; objectName: "guidePageTitle"
                            Layout.fillWidth: true; color: hero.cabinet ? "#fff2d8" : viewer.ink
                            text: viewer.sheet ? viewer.sheet.title : viewer.page === "walk" ?
                                  (viewer.area ? viewer.area.name : viewer.stop.title) : viewer.titleOf(viewer.page)
                            font.pixelSize: viewer.narrow ? (viewer.tv ? 40 : 35) : viewer.tv ? 55 : 47
                            lineHeight: 1.04
                        }
                        Copy {
                            Layout.fillWidth: true; visible: !!text
                            color: hero.cabinet ? "#f1e9d6" : viewer.ink
                            text: viewer.sheet ? viewer.sheet.objective : hero.cabinet ? "Choose up to three specimens to see Ryu’s form and initial AP." : ""
                        }
                    }
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: hero.cabinet ? 3 : 1; color: "#bbac88" }
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
                            onTextEdited: { viewer.query = text; viewer.rememberReadingChoice() }
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
                                text: viewer.currentPlace >= 0 ? viewer.titleOf(fieldGuide.markTarget || viewer.route[viewer.currentPlace].id) : ""
                                detail: fieldGuide.marker >= 0 ? "Your marked place" : viewer.gameStory.source || ""
                                onClicked: viewer.visit(fieldGuide.markTarget || viewer.route[viewer.currentPlace].id)
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
                        visible: viewer.page === "walk" && !!text
                        text: viewer.place !== viewer.currentPlace ? "" : fieldGuide.marker >= 0 ?
                              (!viewer.sheets[fieldGuide.markTarget] || viewer.bookmarkId === fieldGuide.markTarget ? "YOUR MARKED PLACE" : "") :
                              viewer.savedPlace >= 0 && (!viewer.area || viewer.area.name ===
                                 (viewer.savedArea || viewer.areas[0]).name)
                                 ? (viewer.gameStory.source || "").toUpperCase() : ""
                    }
                    Flow {
                        Layout.fillWidth: true; spacing: 5
                        visible: viewer.areas.length > 0
                        Repeater {
                            model: viewer.areas
                            delegate: Action {
                                required property var modelData
                                objectName: "routeArea"+modelData.name; text: modelData.name
                                selected: !!viewer.area && viewer.area.name === text
                                onClicked: viewer.chooseArea(modelData.name)
                            }
                        }
                    }
                    GuideRouteSpread {
                        id: worked; objectName: "workedRoute"
                        reader: viewer; visible: !!viewer.sheet; Layout.fillWidth: true
                    }
                    GridLayout {
                        visible: !viewer.sheet || viewer.readingFloor
                        Layout.fillWidth: true; columns: viewer.narrow ? 1 : 2
                        columnSpacing: 25; rowSpacing: 12
                        ColumnLayout {
                            visible: !viewer.mapExpanded && !viewer.sheet
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
                                visible: !viewer.sheet
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
                                initialMapId: viewer.area && !viewer.area.floorIds.includes(viewer.savedFloor) ? viewer.area.firstFloor : viewer.savedFloor
                                place: viewer.game + "/" + (viewer.stop.id || "") + "/" + (viewer.area ? viewer.area.name : "")
                                status: fieldGuide.floorStatus; accent: viewer.accent; tv: viewer.tv
                                expanded: viewer.mapExpanded
                                onResizeMap: { viewer.mapExpanded = !viewer.mapExpanded; viewer.focusNamed("floorSize") }
                            }
                            Action {
                                visible: !viewer.sheet && viewer.activeSection === "Map" && viewer.schematicAvailable && !!floorSheet.raster
                                text: viewer.overview ? "View floor plans" : "Read route landmarks"; quiet: true
                                onClicked: viewer.overview = !viewer.overview
                            }
                            Title {
                                visible: !viewer.sheet && viewer.activeSection === "Map" && viewer.schematicAvailable && (!floorSheet.raster || viewer.overview)
                                Layout.fillWidth: true; text: "Route landmarks"
                            }
                            FieldAtlas {
                                objectName: "areaAtlas"; Layout.fillWidth: true
                                visible: !viewer.sheet && viewer.activeSection === "Map" && viewer.schematicAvailable && (!floorSheet.raster || viewer.overview)
                                chart: viewer.stop.map || null; accent: viewer.accent; tv: viewer.tv
                            }
                            FieldLedger {
                                Layout.fillWidth: true; visible: ["Items","Enemies"].includes(viewer.activeSection)
                                monsters: viewer.activeSection === "Enemies"
                                records: ((monsters ? viewer.stop.encounters : viewer.stop.items) || []).filter(r => !viewer.area || (r.areaIds || []).includes(viewer.area.id))
                                accent: viewer.accent; tv: viewer.tv
                                onEntryRequested: (row) => viewer.visit(viewer.entityId(row, monsters))
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
                                text: viewer.loreOpen ? "Close field note" : "Field note"
                                onClicked: viewer.loreOpen = !viewer.loreOpen
                            }
                            Copy { Layout.fillWidth: true; visible: viewer.activeSection === "Notes" && viewer.loreOpen; text: viewer.stop.lore || "" }
                        }
                    }
                    ColumnLayout {
                        visible: !!viewer.sheet; Layout.fillWidth: true; spacing: 12
                        Rule {}
                        GridLayout {
                            Layout.fillWidth: true; columns: width < (viewer.tv ? 900 : 720) ? 1 : 2
                            columnSpacing: 21; rowSpacing: 13
                            ColumnLayout {
                                Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.minimumWidth: 0; Layout.alignment: Qt.AlignTop
                                Title { text: "Treasure" }
                                FieldLedger {
                                    Layout.fillWidth: true; records: worked.scopedItems; monsters: false; accent: viewer.accent; tv: viewer.tv
                                    onEntryRequested: (row) => viewer.visit(viewer.entityId(row,false))
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.minimumWidth: 0; Layout.alignment: Qt.AlignTop
                                Title { text: "Encounters" }
                                FieldLedger {
                                    Layout.fillWidth: true; records: worked.scopedEnemies; monsters: true; accent: viewer.accent; tv: viewer.tv
                                    onEntryRequested: (row) => viewer.visit(viewer.entityId(row,true))
                                }
                            }
                        }
                        Action {
                            visible: !!viewer.stop.lore && (!viewer.area || !!viewer.area.lore)
                            objectName: "workedLore"; text: viewer.loreOpen ? "Close field note" : "Field note"; quiet: true
                            onClicked: viewer.loreOpen = !viewer.loreOpen
                        }
                        Copy { visible: viewer.loreOpen; Layout.fillWidth: true; text: viewer.stop.lore || "" }
                        Action {
                            visible: viewer.sheet?.id === "cedar" && !viewer.sheet.nextSheet; quiet: true; objectName: "afterCedar"
                            text: viewer.afterOpen ? "Close the later route" : "After reaching McNeil"
                            onClicked: viewer.afterOpen = !viewer.afterOpen
                        }
                        Repeater {
                            model: viewer.sheet?.id === "cedar" && !viewer.sheet.nextSheet && viewer.afterOpen ? viewer.stop.steps.slice(1) : []
                            delegate: Copy { required property string modelData; text: modelData; Layout.fillWidth: true }
                        }
                    }
                        Image {
                            objectName: "guideFieldFrame"
                            readonly property string frame: fieldGuide.photos[viewer.place] || ""
                            visible: !!frame && (!viewer.sheet || (viewer.readingFloor && viewer.sheet.id === viewer.stop.id))
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
                            readonly property string nextRoute: viewer.sheet?.nextSheet || ""
                            visible: !!nextRoute || viewer.place + 1 < viewer.route.length
                            text: nextRoute ? "Continue to " + (nextRoute === "dam" ? "the Dam" : viewer.titleOf(nextRoute)) : "Read the next stop  ›"
                            onClicked: {
                                if (nextRoute) {
                                    viewer.visit(nextRoute)
                                    viewer.enginesOpen = !!viewer.sheet?.opening
                                } else viewer.changePlace(viewer.place + 1)
                            }
                        }
                        Action {
                            objectName: "guideMark"; Layout.fillWidth: true; quiet: true
                            visible: fieldGuide.marker !== viewer.place || (viewer.sheet && fieldGuide.markTarget !== viewer.bookmarkId)
                            text: "Set my place here"
                            onClicked: { fieldGuide.markArea(viewer.place,viewer.sheet ? viewer.sheet.id : ""); viewer.focusNamed("guideRoute") }
                        }
                        Action {
                            objectName: "followSave"; Layout.fillWidth: true; quiet: true
                            visible: fieldGuide.marker >= 0
                            text: viewer.savedPlace >= 0 ? "Follow my save" : "Clear marked place"
                            onClicked: {
                                fieldGuide.clearMarker()
                                if (fieldGuide.marker < 0) {
                                    if (viewer.savedPlace >= 0) viewer.setPage(viewer.route[viewer.savedPlace].id, true)
                                    else if (viewer.initialReading === FieldGuide.ReadingByChoice) viewer.initialReading = FieldGuide.AwaitingSave
                                }
                            }
                        }
                    }
                }

                ColumnLayout {
                    visible: viewer.page === "genes"
                    Layout.fillWidth: true
                    spacing: 11
                    Rectangle {
                        Layout.fillWidth: true; Layout.leftMargin: -column.x; Layout.rightMargin: -column.x; Layout.topMargin: -column.spacing
                        color: "#163642"; implicitHeight: mineralTray.implicitHeight + 28
                        ColumnLayout {
                            id: mineralTray; x: column.x; y: 4; width: Math.min(parent.width - 2*x, viewer.tv ? 1060 : 800)
                            spacing: 9
                            GridLayout {
                                Layout.fillWidth: true; columns: viewer.narrow ? 1 : 3; columnSpacing: 13; rowSpacing: 8
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
                                        text: modelData.name
                                        detail: modelData.ap + " AP"
                                        art: fieldGuide.plate(modelData.id)
                                        onClicked: viewer.chooseGene(index)
                                    }
                                }
                            }
                        Action {
                            id: allGeneAction
                            objectName: "revealGenes"; visible: viewer.allGenes.length > 3
                            text: viewer.revealNames ? "Hide later gene names" : "Show all " + viewer.allGenes.length + " genes (spoilers)"
                            quiet: true; dark: true; onClicked: viewer.revealNames = !viewer.revealNames
                        }
                        GridLayout {
                            visible: viewer.revealNames && viewer.allGenes.length > 3
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
                                    text: modelData.name
                                    detail: modelData.ap + " AP"
                                    art: fieldGuide.plate(modelData.art)
                                    onClicked: viewer.chooseGene(index+3)
                                }
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
                    Title { text: "In battle" }
                    Copy { Layout.fillWidth: true; Layout.maximumWidth: 780
                        text: "Use Accession to combine genes. The AP beside the form is the cost to transform. Staying in dragon form costs more AP on later turns." }
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
                    Repeater {
                        model: viewer.page === "masters" ? (viewer.book.teachers || []).filter(t =>
                            [viewer.allMasters[viewer.first].name, viewer.allMasters[viewer.second].name].includes(t.name)) : []
                        delegate: ColumnLayout {
                            required property var modelData
                            id: training; Layout.fillWidth: true; Layout.maximumWidth: 870; spacing: 8
                            Rule {}
                            Title { text: training.modelData.name; Layout.fillWidth: true }
                            Copy { text: training.modelData.join; Layout.fillWidth: true }
                            GuideReferenceTable {
                                objectName: "lessons" + training.modelData.id
                                Layout.fillWidth: true; tv: viewer.tv; accent: viewer.accent
                                dataTable: ({title: "Skills", columns: [training.modelData.measure, "Skill"],
                                    rows: training.modelData.lessons.map(s => [s.goal, s.skill])})
                            }
                            Action {
                                objectName: "training" + training.modelData.id
                                text: training.modelData.name + " at " + training.modelData.where
                                quiet: true; onClicked: viewer.visit(training.modelData.id)
                            }
                        }
                    }
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
                    Action {
                        visible: viewer.page === "rwolf" && viewer.known("teacher-rwolf")
                        text: "Rwolf’s skills"; onClicked: viewer.visit("teacher-rwolf")
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
                                art: fieldGuide.plate(viewer.articles.find(a => a.category === modelData)?.art || "")
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
                        onEntryRequested: (row) => viewer.visit(viewer.entityId(row, monsters))
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
                    Repeater {
                        model: viewer.article?.referenceTables || []
                        delegate: GuideReferenceTable {
                            required property var modelData; required property int index
                            objectName: "referenceTable" + index
                            Layout.fillWidth: true; Layout.maximumWidth: 960
                            tv: viewer.tv; accent: viewer.accent; dataTable: modelData
                        }
                    }
                }
                ColumnLayout {
                    visible: !!viewer.entity; Layout.fillWidth: true; Layout.maximumWidth: 860; spacing: 10
                    Title { text: viewer.entity?.category === "Bestiary" ? "Where to fight it" : "Where to find it" }
                    Repeater {
                        model: (viewer.entity?.observations || []).filter(r => viewer.isAvailable(r.stop) || viewer.revealedSubjects.includes(viewer.entity.category))
                        delegate: ColumnLayout {
                            id: sighting
                            required property var modelData
                            Layout.fillWidth: true; spacing: 6
                            Rule {}
                            Copy { Layout.fillWidth: true; text: sighting.modelData.where; font.weight: Font.DemiBold }
                            Copy { Layout.fillWidth: true; text: sighting.modelData.detail }
                            Flow {
                                Layout.fillWidth: true; spacing: 5
                                Repeater {
                                    model: viewer.observationTargets(sighting.modelData)
                                    delegate: Action {
                                        required property string modelData
                                        text: viewer.titleOf(modelData); quiet: true
                                        onClicked: viewer.visit(modelData)
                                    }
                                }
                            }
                        }
                    }
                    Action {
                        visible: !!viewer.entity && !viewer.revealedSubjects.includes(viewer.entity.category)
                                 && viewer.entity.observations.some(r => !viewer.isAvailable(r.stop))
                        text: "Show later locations (spoilers)"; quiet: true
                        onClicked: viewer.revealedSubjects = viewer.revealedSubjects.concat([viewer.entity.category])
                    }
                }
                ColumnLayout {
                    visible: viewer.page === "bookmarks"; Layout.fillWidth: true; spacing: 7
                    Copy { visible: !fieldGuide.pins.length; Layout.fillWidth: true; text: "Choose “Pin this page” on any guide entry to keep it here." }
                    Repeater {
                        model: viewer.page === "bookmarks" ? fieldGuide.pins : []
                        delegate: Action {
                            required property string modelData
                            Layout.fillWidth: true; objectName: "bookmark" + modelData; text: viewer.titleOf(modelData)
                            onClicked: viewer.visit(modelData)
                        }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    readonly property var related: Array.from(new Set((viewer.sheet?.links || []).concat(viewer.subject?.links || []))).filter(id => viewer.isAvailable(id))
                    readonly property var citations: viewer.entity ? Array.from(new Set(viewer.entity.observations
                        .filter(r => viewer.isAvailable(r.stop) || viewer.revealedSubjects.includes(viewer.entity.category))
                        .reduce((list,r) => list.concat(viewer.route.find(s => s.id === r.stop)?.sources || []), []))) : (viewer.subject?.sources || [])
                    id: references
                    visible: !!viewer.subject || !!viewer.entity
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
                        visible: references.citations.length > 0
                        text: viewer.sourcesOpen ? "Hide sources" : "Sources"; quiet: true
                        onClicked: viewer.sourcesOpen = !viewer.sourcesOpen
                    }
                    Repeater {
                        model: viewer.sourcesOpen ? references.citations : []
                        delegate: ColumnLayout {
                            id: sourceRow
                            required property string modelData
                            Layout.fillWidth: true
                            readonly property var citation: viewer.book.sources[modelData]
                            readonly property string chapter: (viewer.subject?.sourceSections || [])
                                .filter(s => s.source === modelData).map(s => s.section).join(" · ")
                            Copy { Layout.fillWidth: true; visible: !sourceRow.citation.url; text: sourceRow.citation.title }
                            Copy { Layout.fillWidth: true; visible: !sourceRow.citation.url && !!sourceRow.chapter; text: sourceRow.chapter }
                            Action {
                                Layout.fillWidth: true; quiet: true; visible: !!sourceRow.citation.url
                                text: sourceRow.citation.title; detail: sourceRow.chapter || "Open source in browser"
                                onClicked: Qt.openUrlExternally(sourceRow.citation.url)
                            }
                        }
                    }
                }
                Rule { visible: viewer.page !== "guide" }
                Action {
                    id: pinAction
                    objectName: "pinEntry"; visible: !["guide","wiki","route","bookmarks"].includes(viewer.page)
                    text: fieldGuide.pins.indexOf(viewer.bookmarkId) >= 0 ? "Remove pin" : "Pin this page"
                    quiet: true
                    onClicked: fieldGuide.togglePin(viewer.bookmarkId)
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
            color: "#17333d"
            Rectangle { width: parent.width; height: 2; color: "#bca16c" }
            RowLayout {
                id: resultRow
                anchors.left: parent.left; anchors.right: parent.right
                anchors.leftMargin: viewer.narrow ? 15 : 30; anchors.rightMargin: anchors.leftMargin
                anchors.verticalCenter: parent.verticalCenter; spacing: 14
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 2
                    Kicker {
                        visible: viewer.chosen.length > 0; Layout.fillWidth: true; color: "#f3cf90"
                        text: viewer.chosen.map(i => (viewer.allGenes[i] || {}).name || "").join("  +  ")
                    }
                    Title { objectName: "geneForm"; Layout.fillWidth: true; color: "#fff1d4"
                        text: viewer.result.form || (viewer.chosen.length ? "Recipe unavailable" : "Choose your first gene") }
                    Copy { Layout.fillWidth: true; visible: !!text; color: "#f4eee0"; font.pixelSize: viewer.tv ? 20 : 16
                        text: viewer.notice || viewer.result.detail || "" }
                }
                ColumnLayout {
                    spacing: 2
                    Kicker { objectName: "geneResult"; color: "#f4cc83"; text: viewer.result.cost !== undefined ? viewer.result.cost + " initial AP" : "" }
                    Action { id: clearGeneButton; objectName: "clearRecipe"; visible: viewer.chosen.length > 0
                        text: "Clear recipe"; dark: true
                        onClicked: { viewer.chosen = []; viewer.notice = ""; viewer.focusNamed("gene0") } }
                }
            }
        }
    }
}
