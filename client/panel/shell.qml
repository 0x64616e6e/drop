//@ pragma UseQApplication
// share panel: a small window for drop (files.este.systems): links, activity, received files, actions.
// Opened and closed by `share panel` (bar click). Data: `share panel-data` (one ssh round trip).
// Colours come from the theme (polybar colours.ini via share). Escape closes.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io

ShellRoot {
    id: root
    property var d: null                    // panel-data JSON
    property string err: ""
    property string notice: ""
    property var c: d ? d.colors : ({ bg: "#121417", block: "#23272E", border: "#2E333C", fg: "#E8DFC9", fg_dim: "#A39C89",
                                       fg_muted: "#6B675C", accent: "#FFA028", on_accent: "#0B0C0E", urgent: "#FF4B3E", ok: "#7FBF5A" })
    readonly property string sans: "IBM Plex Sans"
    readonly property string mono: "BlexMono Nerd Font"

    function when(ts) { return ts ? Qt.formatDateTime(new Date(ts * 1000), "dd MMM HH:mm") : "–" }
    function size(n) {
        const u = ["B", "KB", "MB", "GB"]; let i = 0
        while (n >= 1024 && i < 3) { n /= 1024; i++ }
        return (i ? n.toFixed(1) : n) + " " + u[i]
    }
    readonly property var labels: ({ download: "downloaded", retry: "download retried", viewed: "link opened", refused: "refused (used, expired or unknown link)",
        upload: "file received", "viewed-upload": "upload page opened", badpass: "wrong passphrase", locked: "link locked (wrong passphrases)",
        toolarge: "upload too large", "upload-failed": "upload failed", gc: "clean-up", badpath: "bad address" })

    // ---- data and actions
    Process {
        id: fetch
        command: ["share", "panel-data"]
        running: true
        stdout: StdioCollector {
            onStreamFinished: {
                try { const j = JSON.parse(this.text); if (j.error) root.err = j.error; else { root.d = j; root.err = "" } }
                catch (e) { root.err = "could not read share panel-data" }
            }
        }
    }
    function refresh() { fetch.running = true }
    Process {
        id: action
        property string okText: ""
        stdout: StdioCollector { id: actionOut }
        onExited: (code) => {
            root.notice = code === 0 ? action.okText.replace("%OUT%", actionOut.text.trim().split("\n")[0]) : "failed: " + action.command.join(" ")
            root.refresh()
        }
    }
    function run(cmd, okText) { action.okText = okText; action.command = cmd; action.running = true; root.notice = "working…" }

    // ---- small components
    component Btn: Rectangle {
        id: b
        property string text: ""
        property bool danger: false
        property bool armed: false          // danger buttons need a second click
        signal activated()
        implicitWidth: label.implicitWidth + 16; implicitHeight: 22
        color: armed ? root.c.urgent : area.containsMouse ? root.c.border : root.c.block
        border.color: danger ? root.c.urgent : root.c.border
        Text { id: label; anchors.centerIn: parent; text: b.armed ? "sure?" : b.text; font.family: root.sans; font.pointSize: 8.5
               color: b.armed ? root.c.on_accent : (b.danger ? root.c.urgent : root.c.fg) }
        MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
            onClicked: { if (b.danger && !b.armed) { b.armed = true; disarm.restart() } else { b.armed = false; b.activated() } } }
        Timer { id: disarm; interval: 3000; onTriggered: b.armed = false }
    }
    component Heading: Text {
        font.family: root.sans; font.pointSize: 9; font.bold: true; color: root.c.accent
        Layout.topMargin: 10
    }
    component Line: Text {
        font.family: root.sans; font.pointSize: 9; color: root.c.fg; wrapMode: Text.WordWrap
        Layout.fillWidth: true; textFormat: Text.StyledText
    }

    FloatingWindow {
        title: "share-panel"
        implicitWidth: 560; implicitHeight: 600
        color: root.c.bg
        visible: true

        Shortcut { sequence: "Escape"; onActivated: Qt.quit() }

        ColumnLayout {
            anchors.fill: parent; anchors.margins: 14; spacing: 6

            // header
            RowLayout {
                Layout.fillWidth: true
                Text { text: "󰒗  files.este.systems"; font.family: root.mono; font.pointSize: 11; color: root.c.accent }
                Item { Layout.fillWidth: true }
                Btn { text: "refresh"; onActivated: root.refresh() }
                Btn { text: "close"; onActivated: Qt.quit() }
            }
            Line {
                visible: root.d !== null
                color: root.c.fg_dim
                text: !root.d ? "" : (root.d.status.active_links + " download link" + (root.d.status.active_links === 1 ? "" : "s") + " and "
                      + root.d.status.active_requests + " upload link" + (root.d.status.active_requests === 1 ? "" : "s") + " still work · "
                      + root.d.status.downloads_24h + " download" + (root.d.status.downloads_24h === 1 ? "" : "s") + " in 24 h · certificate "
                      + (root.d.status.cert_days < 20 ? "<font color='" + root.c.urgent + "'>" + root.d.status.cert_days + " days left</font>"
                                                       : "ok (" + root.d.status.cert_days + " days)"))
            }
            RowLayout {
                visible: root.d !== null && root.d.status.unseen > 0
                Line { text: "<font color='" + root.c.accent + "'>" + (root.d ? root.d.status.unseen : 0) + " new</font> since you last looked (downloads, uploads, locked links)"; Layout.fillWidth: true }
                Btn { text: "mark seen"; onActivated: root.run(["share", "seen"], "marked as seen") }
            }
            Line { visible: root.err !== ""; text: root.err; color: root.c.urgent }
            Line { visible: root.d === null && root.err === ""; text: "loading…"; color: root.c.fg_muted }
            Line { visible: root.notice !== ""; text: root.notice; color: root.c.ok }

            ScrollView {
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true
                contentWidth: availableWidth

                ColumnLayout {
                    width: parent.width; spacing: 4

                    // ---- shared files
                    Heading { text: "Shared files" }
                    Line { visible: root.d && root.d.files.length === 0; text: "none"; color: root.c.fg_muted }
                    Repeater {
                        model: root.d ? root.d.files.slice().reverse() : []
                        ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true; spacing: 2
                            RowLayout {
                                Layout.fillWidth: true
                                Line {
                                    text: "<b>" + ((root.d.names || {})[modelData.id] || modelData.name) + "</b>  <font color='" + root.c.fg_dim + "'>" + root.size(modelData.size)
                                          + (modelData.encrypted ? " · encrypted" + (root.d.keys.indexOf(modelData.id) >= 0 ? "" : " (no local key)") : "")
                                          + " · added " + root.when(modelData.added) + "</font>"
                                }
                                Btn { text: "new link"; visible: !modelData.encrypted || root.d.keys.indexOf(modelData.id) >= 0
                                      onActivated: root.run(["sh", "-c", "share link " + modelData.id + " --note panel | head -1 | tee /dev/stderr | tr -d '\\n' | xclip -selection clipboard"],
                                                            "new link copied to the clipboard") }
                                Btn { text: "delete"; danger: true; onActivated: root.run(["share", "rm", modelData.id], "deleted " + ((root.d.names || {})[modelData.id] || modelData.name)) }
                            }
                            Repeater {
                                model: modelData.links
                                RowLayout {
                                    required property var modelData
                                    Layout.fillWidth: true; Layout.leftMargin: 14
                                    Line {
                                        readonly property bool live: modelData.state.indexOf("left") >= 0 || modelData.state === "retry ok"
                                        color: live ? root.c.fg : root.c.fg_muted
                                        text: (live ? "<font color='" + root.c.ok + "'>●</font> " : "○ ") + modelData.state
                                              + (modelData.note ? " · for " + modelData.note : "") + (modelData.passphrase ? " · passphrase" : "")
                                              + " · expires " + root.when(modelData.expires) + " · last used " + root.when(modelData.last_used)
                                    }
                                    Btn { text: "revoke"; danger: true; visible: modelData.state.indexOf("left") >= 0
                                          onActivated: root.run(["share", "revoke", modelData.id], "link " + modelData.id + " revoked") }
                                }
                            }
                        }
                    }

                    // ---- upload links
                    RowLayout {
                        Layout.fillWidth: true
                        Heading { text: "Upload links" }
                        Item { Layout.fillWidth: true }
                        Btn { text: "new upload link"; Layout.topMargin: 10
                              onActivated: root.run(["sh", "-c", "share request --note panel | head -1 | tr -d '\\n' | xclip -selection clipboard"],
                                                    "upload link copied to the clipboard (one file, 7 days, up to 95 MB)") }
                    }
                    Line { visible: root.d && root.d.requests.length === 0; text: "none"; color: root.c.fg_muted }
                    Repeater {
                        model: root.d ? root.d.requests.slice().reverse() : []
                        RowLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            Line {
                                color: modelData.state.indexOf("left") >= 0 ? root.c.fg : root.c.fg_muted
                                text: modelData.state + " · up to " + root.size(modelData.max_size) + (modelData.note ? " · for " + modelData.note : "")
                                      + " · expires " + root.when(modelData.expires) + " · last used " + root.when(modelData.last_used)
                            }
                            Btn { text: "revoke"; danger: true; visible: modelData.state.indexOf("left") >= 0
                                  onActivated: root.run(["share", "revoke", modelData.id], "upload link revoked") }
                        }
                    }

                    // ---- received files
                    Heading { text: "Received files" }
                    Line { visible: root.d && root.d.inbox.length === 0; text: "none"; color: root.c.fg_muted }
                    Repeater {
                        model: root.d ? root.d.inbox : []
                        RowLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            Line { text: "<b>" + modelData.name + "</b>  <font color='" + root.c.fg_dim + "'>" + root.size(modelData.size)
                                         + " · " + root.when(modelData.received) + " from " + modelData.ip + (modelData.note ? " · " + modelData.note : "") + "</font>" }
                            Btn { text: "fetch"; onActivated: root.run(["share", "fetch", modelData.id], "saved: %OUT%") }
                            Btn { text: "delete"; danger: true; onActivated: root.run(["share", "inbox-rm", modelData.id], "deleted " + modelData.name) }
                        }
                    }

                    // ---- activity
                    Heading { text: "Recent activity" }
                    Repeater {
                        model: root.d ? root.d.events : []
                        Line {
                            required property var modelData
                            readonly property bool important: ["download", "upload", "locked", "badpass"].indexOf(modelData.result) >= 0
                            color: important ? root.c.fg : root.c.fg_dim
                            text: root.when(modelData.ts) + "  " + (root.labels[modelData.result] || modelData.result)
                                  + (modelData.name ? " · " + ((root.d.names || {})[modelData.file_id] || modelData.name) : (modelData.note ? " · " + modelData.note : ""))
                                  + (modelData.ip ? "  <font color='" + root.c.fg_muted + "'>" + modelData.ip + "</font>" : "")
                        }
                    }
                }
            }
        }
    }
}
