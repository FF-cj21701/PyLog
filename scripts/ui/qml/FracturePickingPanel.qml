import QtQuick 2.15
import QtQuick.Controls.Basic 2.15
import QtQuick.Layouts 1.15

Item {
    id: root
    readonly property int panelPadding: 14
    readonly property int actionButtonWidth: 78
    readonly property int actionDividerGap: 14
    readonly property int expandedWidth: 440
    readonly property int collapsedWidth: actionButtonWidth + panelPadding * 2
    readonly property int panelHeight: 504

    width: bridge.collapsed ? collapsedWidth : expandedWidth
    height: panelHeight
    clip: false

    property color textColor: bridge.themeText
    property color mutedColor: bridge.themeMuted
    property color dividerColor: bridge.themeDivider
    property color panelBgColor: bridge.panelBg
    property color panelBorderColor: bridge.panelBorder
    property color inputBgColor: bridge.inputBg
    property color inputBorderColor: bridge.inputBorder
    property color buttonBgColor: bridge.buttonBg
    property color buttonHoverColor: bridge.buttonHover
    property color specialButtonBgColor: bridge.specialButtonBg
    property color specialButtonHoverColor: bridge.specialButtonHover
    property color specialButtonTextColor: bridge.specialButtonText
    property color blueColor: bridge.primaryColor
    property color blueHoverColor: bridge.primaryHoverColor
    property color dangerColor: bridge.dangerColor
    property color accentLightColor: bridge.accentLightColor

    Rectangle {
        anchors.fill: parent
        color: root.panelBgColor
    }

    component ToolButton: Rectangle {
        id: buttonRoot
        property string label: ""
        property color accent: root.blueColor
        property bool primary: false
        property bool softAccent: false
        property bool actionEnabled: true
        signal clicked()

        width: parent ? parent.width : 110
        height: primary ? 58 : 30
        radius: 7
        color: primary ? root.blueColor
              : softAccent ? (mouseArea.containsMouse ? root.specialButtonHoverColor : root.specialButtonBgColor)
              : (mouseArea.containsMouse ? root.buttonHoverColor : root.buttonBgColor)
        border.color: primary ? root.blueHoverColor : root.inputBorderColor
        border.width: 1
        opacity: actionEnabled ? 1.0 : 0.45

        Text {
            anchors.fill: parent
            text: buttonRoot.label
            color: buttonRoot.primary ? "#ffffff"
                   : buttonRoot.softAccent ? root.specialButtonTextColor
                   : (buttonRoot.accent === root.dangerColor ? root.dangerColor : root.textColor)
            font.pixelSize: buttonRoot.primary ? 14 : 12
            font.bold: buttonRoot.primary
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }

        MouseArea {
            id: mouseArea
            anchors.fill: parent
            hoverEnabled: true
            enabled: buttonRoot.actionEnabled
            onClicked: buttonRoot.clicked()
        }
    }

    component ButtonGroupSeparator: Item {
        width: parent ? parent.width : 86
        height: 8

        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            height: 1
            color: root.dividerColor
        }
    }

    component PickCombo: ComboBox {
        id: combo
        height: 34
        font.pixelSize: 12

        background: Rectangle {
            radius: 6
            color: root.inputBgColor
            border.color: combo.activeFocus ? root.blueColor : root.inputBorderColor
            border.width: 1
        }

        contentItem: Text {
            text: combo.displayText
            color: root.textColor
            font: combo.font
            leftPadding: 12
            rightPadding: 24
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }

        indicator: Text {
            x: combo.width - width - 12
            y: (combo.height - height) / 2
            text: "v"
            color: root.mutedColor
            font.pixelSize: 12
            font.bold: true
        }

        popup: Popup {
            y: combo.height + 2
            width: combo.width
            implicitHeight: Math.min(contentItem.implicitHeight, 180)
            padding: 1
            contentItem: ListView {
                clip: true
                implicitHeight: contentHeight
                model: combo.popup.visible ? combo.delegateModel : null
                currentIndex: combo.highlightedIndex
            }
            background: Rectangle {
                color: root.inputBgColor
                border.color: root.inputBorderColor
                radius: 6
            }
        }

        delegate: ItemDelegate {
            width: combo.width - 2
            height: 28
            padding: 6

            contentItem: Text {
                text: modelData
                color: highlighted ? root.blueColor : root.textColor
                font.pixelSize: 12
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }

            background: Rectangle {
                radius: 4
                color: highlighted ? root.accentLightColor : "transparent"
            }
        }
    }

    component PickField: TextField {
        id: field
        height: 34
        font.pixelSize: 12
        color: root.textColor
        selectedTextColor: "#ffffff"
        selectionColor: root.blueColor
        verticalAlignment: TextInput.AlignVCenter
        leftPadding: 12
        rightPadding: 12

        background: Rectangle {
            radius: 6
            color: root.inputBgColor
            border.color: field.activeFocus ? root.blueColor : root.inputBorderColor
            border.width: 1
        }
    }

    component InfoButton: Rectangle {
        id: infoButton
        property string label: ""
        signal clicked()

        height: 32
        radius: 6
        color: infoMouse.containsMouse ? root.buttonHoverColor : root.buttonBgColor
        border.color: root.inputBorderColor
        border.width: 1

        Text {
            anchors.fill: parent
            text: infoButton.label
            color: root.textColor
            font.pixelSize: 12
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }

        MouseArea {
            id: infoMouse
            anchors.fill: parent
            hoverEnabled: true
            onClicked: infoButton.clicked()
        }
    }

    Rectangle {
        id: panel
        x: 0
        y: 0
        width: root.width
        height: root.height
        radius: 10
        color: root.panelBgColor
        border.color: root.panelBorderColor
        border.width: 1
        clip: true

        MouseArea {
            id: dragArea
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton
            onPressed: function(mouse) {
                bridge.beginDrag(mouse.x, mouse.y)
            }
            onPositionChanged: function(mouse) {
                if (dragArea.pressed)
                    bridge.dragTo(mouse.x, mouse.y)
            }
            onReleased: bridge.endDrag()
            onCanceled: bridge.endDrag()
        }

        Row {
            anchors.fill: parent
            anchors.margins: root.panelPadding
            spacing: bridge.collapsed ? 0 : root.actionDividerGap

            Item {
                id: infoPanel
                width: bridge.collapsed ? 0 : parent.width - actionPanel.width - root.actionDividerGap
                height: parent.height
                visible: !bridge.collapsed
                enabled: !bridge.collapsed
                clip: true

                Column {
                    anchors.fill: parent
                    spacing: 0

                    Row {
                        width: parent.width
                        height: 48
                        spacing: 8

                        Text {
                            height: parent.height
                            width: parent.width - 30
                            text: "Fracture Picking"
                            color: root.textColor
                            font.pixelSize: 20
                            font.bold: true
                            elide: Text.ElideRight
                            verticalAlignment: Text.AlignVCenter
                        }

                        Text {
                            width: 22
                            height: parent.height
                            text: ">"
                            color: root.mutedColor
                            font.pixelSize: 22
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter

                            MouseArea {
                                anchors.fill: parent
                                hoverEnabled: true
                                onClicked: bridge.setCollapsed(true)
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 1
                        color: root.dividerColor
                    }

                    Column {
                        width: parent.width
                        spacing: 16
                        topPadding: 16

                        Row {
                            width: parent.width
                            height: 50
                            spacing: 22
                            Text {
                                width: 96
                                height: parent.height
                                text: "Type"
                                color: root.textColor
                                font.pixelSize: 14
                                font.bold: true
                                verticalAlignment: Text.AlignVCenter
                            }
                            PickCombo {
                                width: parent.width - 118
                                anchors.verticalCenter: parent.verticalCenter
                                model: bridge.fractureTypeLabels
                                onActivated: bridge.setFractureType(currentText)
                            }
                        }

                        Rectangle {
                            width: parent.width
                            height: 1
                            color: root.dividerColor
                        }

                        Row {
                            width: parent.width
                            height: 50
                            spacing: 22
                            Text {
                                width: 96
                                height: parent.height
                                text: "Display on"
                                color: root.textColor
                                font.pixelSize: 14
                                font.bold: true
                                verticalAlignment: Text.AlignVCenter
                            }
                            PickCombo {
                                width: parent.width - 118
                                anchors.verticalCenter: parent.verticalCenter
                                model: bridge.targetLabels
                                currentIndex: bridge.currentTargetIndex
                                onActivated: bridge.setTargetIndex(index)
                            }
                        }

                        Rectangle {
                            width: parent.width
                            height: 1
                            color: root.dividerColor
                        }

                        Row {
                            width: parent.width
                            height: 50
                            spacing: 22
                            Text {
                                width: 96
                                height: parent.height
                                text: "Borehole Dia."
                                color: root.textColor
                                font.pixelSize: 14
                                font.bold: true
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                            }
                            Row {
                                width: parent.width - 118
                                height: parent.height
                                spacing: 8
                                PickField {
                                    id: boreholeDiameterField
                                    width: parent.width - 28
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: bridge.boreholeDiameterText
                                    inputMethodHints: Qt.ImhFormattedNumbersOnly
                                    validator: DoubleValidator {
                                        bottom: 0.001
                                        top: 999.0
                                        decimals: 3
                                        notation: DoubleValidator.StandardNotation
                                    }
                                    onEditingFinished: bridge.setBoreholeDiameter(text)
                                }
                                Text {
                                    width: 20
                                    height: parent.height
                                    text: "in"
                                    color: root.mutedColor
                                    font.pixelSize: 12
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }
                        }

                        Rectangle {
                            width: parent.width
                            height: 1
                            color: root.dividerColor
                        }

                    }
                }

                InfoButton {
                    width: 96
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    label: "Results"
                    onClicked: bridge.showResults()
                }

                Text {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.rightMargin: 108
                    anchors.bottom: parent.bottom
                    height: 32
                    text: bridge.autoDetectionStatus
                    color: root.mutedColor
                    font.pixelSize: 11
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight

                    MouseArea {
                        anchors.fill: parent
                        enabled: bridge.autoDetectionStatus.length > 0
                        hoverEnabled: true
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: bridge.showAutoDetectionMonitor()
                    }
                }
            }

            Item {
                id: actionPanel
                width: bridge.collapsed
                       ? root.actionButtonWidth
                       : root.actionButtonWidth + root.actionDividerGap + 1
                height: parent.height

                Rectangle {
                    width: 1
                    height: parent.height
                    color: root.dividerColor
                    visible: !bridge.collapsed
                }

                Column {
                    id: actionColumn
                    width: root.actionButtonWidth
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 6

                    ToolButton {
                        label: "Finish"
                        primary: true
                        actionEnabled: !bridge.autoDetectionRunning
                        ToolTip.visible: false
                        onClicked: bridge.finish()
                    }

                    ButtonGroupSeparator {}

                    ToolButton {
                        label: "Undo"
                        actionEnabled: !bridge.autoDetectionRunning
                        onClicked: bridge.undo()
                    }

                    ToolButton {
                        label: "Delete"
                        actionEnabled: !bridge.autoDetectionRunning
                        accent: root.dangerColor
                        onClicked: bridge.deleteSelected()
                    }

                    ToolButton {
                        label: "Clear All"
                        actionEnabled: !bridge.autoDetectionRunning
                        onClicked: bridge.clearAll()
                    }

                    ToolButton {
                        label: "Cancel"
                        actionEnabled: !bridge.autoDetectionRunning
                        onClicked: bridge.cancel()
                    }

                    ToolButton {
                        label: bridge.autoDetectionButtonText
                        softAccent: true
                        onClicked: bridge.toggleAutoDetection()
                    }

                    ButtonGroupSeparator {}

                    ToolButton {
                        label: "Save"
                        actionEnabled: !bridge.autoDetectionRunning
                        onClicked: bridge.saveResults()
                    }

                    ToolButton {
                        label: "Load"
                        actionEnabled: !bridge.autoDetectionRunning
                        onClicked: bridge.loadResults()
                    }

                    ButtonGroupSeparator {}

                    ToolButton {
                        label: "Tadpole"
                        softAccent: true
                        actionEnabled: !bridge.autoDetectionRunning
                        onClicked: bridge.showTadpoleTrack()
                    }

                    ButtonGroupSeparator {}

                    ToolButton {
                        label: "Settings"
                        onClicked: bridge.setCollapsed(!bridge.collapsed)
                    }

                    ToolButton {
                        label: "Exit"
                        onClicked: bridge.exitMode()
                    }
                }
            }
        }
    }
}
