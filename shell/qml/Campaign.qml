import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: book
    required property var host
    readonly property bool third: host.iii
    readonly property bool compact: width < 720
    readonly property bool stacked: !third && (compact || (host.tv && width < 940))
    readonly property color binding: third ? "#162e52" : "#282b28"
    readonly property color ivory: "#fff6df"
    readonly property color secondary: third ? "#d4e5f2" : "#eadbc0"
    readonly property string branchLabel: host.lab || (host.preferredRoute && host.preferredRoute !== "play")
                                         ? (host.currentCampaign ? "Lab copy" : "Lab") : "Original"
    property alias primaryButton: primary
    readonly property bool artworkReady: painting.status === Image.Ready
    spacing: host.tv ? 21 : 16

    component Command: Button {
        id: cmd
        property bool walkable: true
        property bool principal: false
        property bool night: false
        focusPolicy: Qt.StrongFocus
        horizontalPadding: principal ? 22 : 11
        verticalPadding: host.tv ? 12 : 8
        implicitHeight: Math.max(host.tv ? 54 : 44, contentItem.implicitHeight + verticalPadding * 2)
        Accessible.name: text
        contentItem: Text {
            text: cmd.text
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            font.family: host.bodyFace
            font.pixelSize: host.tv ? 21 : 16
            font.weight: Font.DemiBold
            color: cmd.principal ? book.binding : cmd.night ? book.ivory : host.accent
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: Text.AlignHCenter
        }
        background: Rectangle {
            color: cmd.principal ? (cmd.hovered ? "#ffffff" : "#f4e7c4")
                : cmd.hovered ? (cmd.night ? "#404949" : host.raised) : "transparent"
            radius: 2
            border.width: cmd.activeFocus ? 3 : cmd.night && !cmd.principal ? 1 : 0
            border.color: cmd.activeFocus ? (cmd.night ? "#ffb348" : host.focusColor) : "#839198"
        }
        Keys.onReturnPressed: event => { if (!event.isAutoRepeat && enabled) clicked(); event.accepted = true }
        Keys.onEnterPressed: event => { if (!event.isAutoRepeat && enabled) clicked(); event.accepted = true }
    }
    component Imprint: Text {
        color: book.secondary
        font.family: host.labelFace
        font.pixelSize: host.tv ? 19 : 15
        font.letterSpacing: 1.1
        textFormat: Text.PlainText
    }
    Rectangle {
        id: cover
        Layout.fillWidth: true
        readonly property int inset: book.compact ? 20 : 34
        readonly property int imageHeight: book.third ? (book.compact ? 160 : Math.min(279, Math.max(180, host.height * .32))) : 180
        Layout.preferredHeight: book.third || book.stacked ? imageHeight + commands.implicitHeight + inset * 1.4 :
            Math.max(334, commands.implicitHeight + 64)
        color: book.binding
        clip: true
        Image {
            id: painting
            objectName: "campaignPlate"
            x: 0; y: 0
            width: book.third || book.stacked ? parent.width : Math.round(parent.width * .55)
            height: book.third || book.stacked ? cover.imageHeight : parent.height
            fillMode: Image.PreserveAspectCrop
            verticalAlignment: Image.AlignTop
            source: fieldGuide.plate(book.third ? "highlands" : "sandsea")
            smooth: true; mipmap: true
            Accessible.ignored: true
        }
        Rectangle {
            anchors.fill: painting; visible: book.third
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: "#df102237" }
                GradientStop { position: .52; color: "#64122537" }
                GradientStop { position: .86; color: "transparent" }
            }
        }
        Column {
            anchors.left: painting.left; anchors.leftMargin: cover.inset
            anchors.right: painting.right; anchors.rightMargin: cover.inset
            anchors.bottom: painting.bottom; anchors.bottomMargin: cover.inset * .8
            visible: book.third; spacing: 4
            Imprint { text: "CAMPAIGN  /  III"; color: "#f3e9cc" }
            Text {
                objectName: "campaignTitleIII"; text: host.model.title
                width: parent.width; font.family: host.displayFace; font.pixelSize: book.compact ? 38 : host.tv ? 64 : 58
                textFormat: Text.PlainText; wrapMode: Text.WordWrap; color: book.ivory
                Accessible.role: Accessible.Heading
            }
        }
        Rectangle {
            x: book.third || book.stacked ? 0 : painting.width
            y: book.third || book.stacked ? painting.height : 0
            width: book.third || book.stacked ? parent.width : 3
            height: book.third || book.stacked ? 3 : parent.height
            color: book.third ? "#b6925a" : "#a65b48"
        }
        ColumnLayout {
            id: commands
            x: book.third || book.stacked ? cover.inset : painting.width + cover.inset
            width: cover.width - x - cover.inset
            y: book.third || book.stacked ? painting.height + cover.inset * .7 : (cover.height - implicitHeight) / 2
            spacing: host.tv ? 7 : 5
            Imprint { visible: !book.third; text: "CAMPAIGN  /  IV"; color: "#f0c6a2" }
            Text {
                visible: !book.third; objectName: "campaignTitleIV"; text: host.model.title
                Layout.fillWidth: true; wrapMode: Text.WordWrap
                font.family: host.displayFace; font.pixelSize: book.compact ? 34 : host.tv ? 49 : 43
                color: book.ivory; Accessible.role: Accessible.Heading
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 10
                Text {
                    Layout.fillWidth: true; text: host.savedPlace || host.cardCaption() || host.statusHead() || (host.model.playing ? "Game running" : "New game")
                    font.family: host.bodyFace; font.pixelSize: host.tv ? 24 : 19; font.weight: Font.DemiBold
                    color: book.ivory; wrapMode: Text.WordWrap; textFormat: Text.PlainText
                }
                Imprint { text: book.branchLabel }
            }
            Text {
                Layout.fillWidth: true; visible: !!host.savedPlace && !!host.cardCaption()
                text: "Memory card  ·  " + host.cardCaption(); color: book.secondary; font.family: host.bodyFace
                font.pixelSize: host.tv ? 20 : 16; wrapMode: Text.WordWrap; textFormat: Text.PlainText
            }
            Text {
                Layout.fillWidth: true; visible: !!text; text: host.statusCopy()
                font.family: host.bodyFace; font.pixelSize: host.tv ? 21 : 16
                color: book.secondary; lineHeight: 1.13; wrapMode: Text.WordWrap; textFormat: Text.PlainText
            }
            Flow {
                Layout.fillWidth: true; Layout.topMargin: host.tv ? 7 : 5; spacing: 8
                Command {
                    id: primary; objectName: "primary"; principal: true; night: true
                    text: host.mainLabel(); enabled: !host.model.job.phase && (!host.model.playing || host.model.guideAvailable)
                    onClicked: host.playAction()
                }
                Command { objectName: "saves"; text: "Saves"; night: true; enabled: !host.busy
                    visible: !!host.model.record || host.model.points.length > 0 || host.model.restored.length > 0
                    onClicked: host.openSheet("saves") }
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Text {
            Layout.fillWidth: true; text: "Field Guide"; color: host.ink
            font.family: host.displayFace; font.pixelSize: host.tv ? 34 : 29; Accessible.role: Accessible.Heading
        }
        Command { text: "Contents"; enabled: !host.model.job.phase; onClicked: host.openBook("guide") }
    }
    component Reading: Button {
        id: link
        required property string caption
        required property string art
        property bool walkable: true
        Layout.fillWidth: true; Layout.preferredWidth: 1
        implicitHeight: Math.max(host.tv ? 90 : 75, labels.implicitHeight + 18)
        focusPolicy: Qt.StrongFocus; Accessible.name: text + ". " + caption
        horizontalPadding: 1; verticalPadding: 5
        background: Rectangle {
            color: link.hovered ? host.raised : "transparent"
            border.width: link.activeFocus ? 3 : 0; border.color: host.focusColor
            Rectangle { height: 1; width: parent.width; anchors.bottom: parent.bottom; color: host.line }
        }
        contentItem: RowLayout {
            spacing: book.compact ? 10 : 16
            Image {
                Layout.preferredWidth: book.compact ? 56 : 92; Layout.fillHeight: true
                source: fieldGuide.plate(link.art); fillMode: Image.PreserveAspectCrop; mipmap: true; Accessible.ignored: true
            }
            ColumnLayout {
                id: labels; Layout.fillWidth: true; spacing: 2
                Text { Layout.fillWidth: true; text: link.text; font.family: host.displayFace; font.pixelSize: host.tv ? 25 : 21; color: host.ink; wrapMode: Text.WordWrap }
                Text { Layout.fillWidth: true; text: link.caption; font.family: host.bodyFace; font.pixelSize: host.tv ? 20 : 15; color: host.muted; wrapMode: Text.WordWrap }
            }
            Text { text: "›"; font.pixelSize: 24; color: host.accent; rightPadding: 6; Accessible.ignored: true }
        }
        Keys.onReturnPressed: event => { if (!event.isAutoRepeat && enabled) clicked(); event.accepted = true }
        Keys.onEnterPressed: event => { if (!event.isAutoRepeat && enabled) clicked(); event.accepted = true }
    }
    GridLayout {
        Layout.fillWidth: true; columns: book.compact ? 1 : 2; columnSpacing: 24; rowSpacing: 6
        Reading {
            objectName: "campaignWalkthrough"; text: "Walkthrough"
            caption: host.readingMark.title ? "Reading mark · " + host.readingMark.title : host.savedPlace || "Find your place"
            art: book.third ? "iii-woods" : "iv-river"; enabled: !host.model.job.phase
            onClicked: host.openBook(host.readingMark.id || (host.savedPlace ? "guide" : "walk"))
        }
        Reading {
            objectName: "campaignMechanic"; text: book.third ? "Dragon genes" : "Masters"
            caption: book.third ? "Try a combination" : "Lessons and growth"
            art: book.third ? "flame" : "iv-training"; enabled: !host.model.job.phase
            onClicked: host.openBook(book.third ? "genes" : "masters")
        }
    }
    RowLayout {
        Layout.fillWidth: true; visible: host.model.guideAvailable && !!host.preferredRoute
        Text { Layout.fillWidth: true; text: "Open the guide in game  ·  " + host.shortcutText("guide"); color: host.muted; font.family: host.bodyFace; font.pixelSize: host.tv ? 20 : 16; wrapMode: Text.WordWrap }
        Command { objectName: "campaignGuideShortcut"; text: "Change shortcut"; enabled: !host.busy; onClicked: { host.shortcutId = "guide"; host.openSheet("shortcut") } }
    }
}
