import QtQuick 2.15
import QtQuick.Controls.Basic 2.15
import QtQuick.Layouts 1.15

Item {
    id: root
    width: bridge.collapsed ? 128 : 480
    height: 365
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
        signal clicked()

        width: parent ? parent.width : 110
        height: primary ? 58 : 32
        radius: 7
        color: primary ? root.blueColor : (mouseArea.containsMouse ? root.buttonHoverColor : root.buttonBgColor)
        border.color: primary ? root.blueHoverColor : root.inputBorderColor
        border.width: 1

        Text {
            anchors.fill: parent
            text: buttonRoot.label
            color: buttonRoot.primary ? "#ffffff" : (buttonRoot.accent === root.dangerColor ? root.dangerColor : root.textColor)
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
            onClicked: buttonRoot.clicked()
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

    Rectangle {
        id: panel
        x: 0
        y: 0
        width: bridge.collapsed ? 128 : root.width
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
            anchors.leftMargin: bridge.collapsed ? 0 : 14
            anchors.rightMargin: 14
            anchors.topMargin: 14
            anchors.bottomMargin: 14
            spacing: 14

            Item {
                id: infoPanel
                width: bridge.collapsed ? 0 : parent.width - actionPanel.width - 14
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
                    }
                }
            }

            Item {
                id: actionPanel
                width: 114
                height: parent.height

                Rectangle {
                    width: 1
                    height: parent.height
                    color: root.dividerColor
                    visible: true
                }

                Column {
                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.topMargin: 0
                    spacing: 8

                    ToolButton {
                        label: "Finish"
                        primary: true
                        ToolTip.visible: false
                        onClicked: bridge.finish()
                    }

                    ToolButton {
                        label: "Undo"
                        onClicked: bridge.undo()
                    }

                    ToolButton {
                        label: "Unselect"
                        onClicked: bridge.clearSelection()
                    }

                    ToolButton {
                        label: "Delete"
                        accent: root.dangerColor
                        onClicked: bridge.deleteSelected()
                    }

                    ToolButton {
                        label: "Clear All"
                        onClicked: bridge.clearAll()
                    }

                    ToolButton {
                        label: "Cancel"
                        onClicked: bridge.cancel()
                    }

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
