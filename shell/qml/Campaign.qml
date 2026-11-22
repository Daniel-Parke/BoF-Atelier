import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: campaign
    required property var host
    readonly property bool third: host.iii
    readonly property bool narrow: width < 730
    readonly property bool compact: width < 620
    readonly property color pageInk: third ? "#233e35" : "#fff4dd"
    readonly property color pageMuted: third ? "#3e5449" : "#e1cbb5"
    property alias primaryButton: primary
    readonly property bool artworkReady: painting.status === Image.Ready
    spacing: host.tv ? 17 : 12

    component CampaignAction: Button {
        id: action
        property bool walkable: true
        property bool lead: false
        property bool onHero: false
        horizontalPadding: lead ? 22 : 11
        verticalPadding: 9
        focusPolicy: Qt.StrongFocus
        opacity: enabled ? 1 : .62
        implicitHeight: Math.max(host.tv ? 54 : 43, contentItem.implicitHeight + 18)
        Accessible.name: text
        contentItem: Text {
            text: action.text; textFormat: Text.PlainText
            color: action.lead ? (third ? "#fffbed" : "#382723") : action.onHero ? pageInk : host.accent
            font.family: "Segoe UI"; font.pixelSize: host.tv ? 19 : 16; font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 3
            color: action.lead ? (third ? (action.hovered ? "#194333" : "#285640") : (action.hovered ? "#fff6d9" : "#f2deb7"))
                    : action.hovered && !action.onHero ? "#e8e8dc" : "transparent"
            border.width: action.activeFocus ? 3 : 1
            border.color: action.activeFocus ? (action.onHero && !third ? "#ffc264" : host.focusColor)
                         : action.onHero && !action.lead ? pageMuted : "transparent"
        }
        Keys.onReturnPressed: event => { if (!event.isAutoRepeat && enabled) clicked(); event.accepted = true }
        Keys.onEnterPressed: event => { if (!event.isAutoRepeat && enabled) clicked(); event.accepted = true }
    }

    Rectangle {
        id: cover
        Layout.fillWidth: true
        Layout.preferredHeight: Math.max(compact ? 232 : Math.min(448, Math.max(270, host.height * .46)), copy.implicitHeight + (compact ? 36 : 64))
        clip: true
        color: third ? "#ecebdb" : "#342923"
        Image {
            id: painting
            objectName: "campaignPlate"
            x: third ? parent.width - width : 0
            width: parent.width * (compact ? .43 : .56); height: parent.height
            fillMode: Image.PreserveAspectCrop
            horizontalAlignment: third ? Image.AlignRight : Image.AlignHCenter
            verticalAlignment: Image.AlignTop
            source: fieldGuide.plate(third ? "highlands" : "sandsea")
            smooth: true; mipmap: true
            Accessible.ignored: true
        }
        Rectangle {
            x: third ? painting.x - 1 : painting.width - width + 1
            width: Math.max(28, painting.width * .18); height: parent.height
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: third ? cover.color : "transparent" }
                GradientStop { position: 1; color: third ? "transparent" : cover.color }
            }
        }
        ColumnLayout {
            id: copy
            width: cover.width * (compact ? .57 : .47) - (compact ? 28 : 55)
            x: third ? (compact ? 16 : 32) : cover.width - width - (compact ? 16 : 32)
            anchors.verticalCenter: parent.verticalCenter
            spacing: host.tv ? 12 : 8
            Text {
                text: (host.lab || (host.preferredRoute && host.preferredRoute !== "play") ? "LAB CAMPAIGN" : "CAMPAIGN") + "   /   ORIGINAL"
                color: pageMuted; font.family: "Segoe UI"; font.weight: Font.DemiBold
                font.letterSpacing: 1.5; font.pixelSize: host.tv ? 15 : 12
            }
            Text {
                objectName: "campaignTitle"; text: host.model.title; Layout.fillWidth: true
                font.family: third ? "Georgia" : "Palatino Linotype"; font.weight: Font.Normal
                font.pixelSize: compact ? 34 : narrow ? 42 : host.tv ? 62 : 58
                color: pageInk; lineHeight: .95; wrapMode: Text.WordWrap
                Accessible.role: Accessible.Heading
            }
            Text {
                Layout.fillWidth: true
                text: host.statusCopy() || (host.currentCampaign ? host.currentCampaign.title : "Original rules, artwork and music.")
                font.family: "Segoe UI"; font.pixelSize: host.tv ? 21 : 16
                color: pageMuted; wrapMode: Text.WordWrap; textFormat: Text.PlainText
            }
            Flow {
                Layout.fillWidth: true; Layout.topMargin: 3; spacing: 7
                CampaignAction {
                    id: primary; objectName: "primary"; lead: true; onHero: true
                    text: host.mainLabel(); enabled: !host.busy
                    onClicked: host.playAction()
                }
                CampaignAction {
                    objectName: "resume"; onHero: true; text: "Resume"
                    visible: host.model.checkpoints.length > 0; enabled: !host.busy
                    onClicked: host.playSavedCopy("resumeCheckpoint", host.model.checkpoints.includes("suspend") ? "suspend" : "quick")
                }
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Text {
            Layout.fillWidth: true; text: "Field guide"; color: host.ink
            font.family: "Georgia"; font.pixelSize: host.tv ? 31 : 27
            Accessible.role: Accessible.Heading
        }
        CampaignAction { text: "Browse guide"; enabled: !host.busy; onClicked: host.openBook("guide") }
    }
    component Article: Button {
        id: article
        required property string subtitle
        required property string picture
        property bool walkable: true
        Layout.fillWidth: true; Layout.preferredWidth: 1
        implicitHeight: Math.max(host.tv ? 100 : 83, labels.implicitHeight + 18)
        focusPolicy: Qt.StrongFocus; Accessible.name: text + ". " + subtitle
        contentItem: Item {
            Image {
                id: vignette
                visible: !!article.picture
                height: parent.height - 4; width: campaign.compact ? 41 : Math.min(91, height * 1.22)
                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                source: fieldGuide.plate(article.picture); fillMode: Image.PreserveAspectCrop
                smooth: true; mipmap: true; Accessible.ignored: true
            }
            Rectangle {
                visible: !article.picture
                anchors.fill: vignette; color: "#efe5d5"; Accessible.ignored: true
                Column {
                    anchors.centerIn: parent; spacing: 5
                    Repeater {
                        model: [26, 18, 30, 22]
                        Rectangle { required property int modelData; width: modelData; height: 2; color: "#8b6759" }
                    }
                }
            }
            Column {
                id: labels; anchors.left: vignette.right; anchors.leftMargin: campaign.compact ? 8 : 13
                anchors.right: parent.right; anchors.rightMargin: 4; anchors.verticalCenter: parent.verticalCenter; spacing: 3
                Text { text:article.text; width:parent.width; wrapMode:Text.WordWrap; font.family:"Georgia"; font.pixelSize:host.tv ? 24 : 20; color:host.ink }
                Text { text:article.subtitle; width:parent.width; wrapMode:Text.WordWrap; font.family:"Segoe UI"; font.pixelSize:host.tv ? 17 : 14; color:host.muted }
            }
        }
        background: Rectangle {
            color: article.hovered ? "#eeeee2" : host.surface
            border.color: article.activeFocus ? host.focusColor : host.line; border.width: article.activeFocus ? 3 : 1
        }
        Keys.onReturnPressed: event => { if (!event.isAutoRepeat && enabled) clicked(); event.accepted = true }
        Keys.onEnterPressed: event => { if (!event.isAutoRepeat && enabled) clicked(); event.accepted = true }
    }
    GridLayout {
        Layout.fillWidth: true; columns: campaign.compact && host.tv ? 1 : 2; columnSpacing: 13; rowSpacing: 9
        Article {
            objectName: "campaignMechanic"; enabled: !host.busy
            text: third ? "Dragon genes" : "Masters"
            subtitle: third ? "Build a combination" : "Compare apprentice growth"
            picture: third ? "flame" : "iv-training"
            onClicked: host.openBook(third ? "genes" : "masters")
        }
        Article {
            objectName: "campaignWalkthrough"; enabled: !host.busy; text: "Walkthrough"
            subtitle: "Find your place"; picture: third ? "iii-woods" : "iv-wreck"
            onClicked: host.openBook("walk")
        }
    }
    RowLayout {
        visible: host.model.guideAvailable && !!host.preferredRoute
        Layout.fillWidth: true; spacing: 8
        Text {
            Layout.fillWidth: true; text: "In-game guide   ·   " + host.shortcutText("guide")
            wrapMode: Text.WordWrap; font.family: "Segoe UI"; font.pixelSize: host.tv ? 18 : 15; color: host.muted
        }
        CampaignAction {
            objectName: "campaignGuideShortcut"; text: "Change shortcut"; enabled: !host.busy
            onClicked: { host.shortcutId = "guide"; host.openSheet("shortcut") }
        }
    }
}
