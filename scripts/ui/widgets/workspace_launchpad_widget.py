from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget, QHBoxLayout, QGraphicsDropShadowEffect


def parse_curve_mime_payload(raw_data):
    curves = []
    for chunk in [part for part in (raw_data or "").split("|") if part]:
        parts = chunk.split(":")
        if len(parts) < 3:
            continue
        try:
            curves.append({
                "well_id": int(parts[0]),
                "curve_id": int(parts[1]),
                "db_path": ":".join(parts[2:]),
            })
        except ValueError:
            continue
    return curves


@dataclass(frozen=True)
class WorkspaceLaunchAction:
    key: str
    title: str


class WorkspaceLaunchTile(QWidget):
    curves_dropped = Signal(str)
    clicked = Signal(str)
    _GLOW_PADDING = 6
    _TILE_WIDTH = 260
    _TILE_HEIGHT = 120
    _TILE_RADIUS = 16
    _TITLE_SIZE_NORMAL = 20
    _TITLE_SIZE_HOVER = 24
    _TITLE_SIZE_DRAG = 24

    def __init__(self, action_key, title, parent=None):
        super().__init__(parent)
        self._action_key = action_key
        self._hovered = False
        self._drag_over = False
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WA_StyledBackground)
        self.setAttribute(Qt.WA_Hover, True)
        self.setMouseTracking(True)
        self.setObjectName("workspaceLaunchTile")
        self.setFixedSize(
            self._TILE_WIDTH + self._GLOW_PADDING * 2,
            self._TILE_HEIGHT + self._GLOW_PADDING * 2,
        )
        self._glow_effect = QGraphicsDropShadowEffect(self)
        self._glow_effect.setOffset(0, 0)
        self._glow_effect.setBlurRadius(0)
        self._glow_effect.setColor(QColor(255, 255, 255, 0))
        self.setGraphicsEffect(self._glow_effect)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            22 + self._GLOW_PADDING,
            18 + self._GLOW_PADDING,
            22 + self._GLOW_PADDING,
            18 + self._GLOW_PADDING,
        )
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("workspaceLaunchTileTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self._title_font = QFont()
        self._title_font.setPixelSize(self._TITLE_SIZE_NORMAL)
        self._title_font.setWeight(QFont.Black)
        self.title_label.setFont(self._title_font)
        layout.addWidget(self.title_label)
        self._update_title_font()
        self._update_glow_effect()

    def _update_title_font(self):
        if self._drag_over:
            pixel_size = self._TITLE_SIZE_DRAG
        elif self._hovered:
            pixel_size = self._TITLE_SIZE_HOVER
        else:
            pixel_size = self._TITLE_SIZE_NORMAL
        if self._title_font.pixelSize() != pixel_size:
            self._title_font.setPixelSize(pixel_size)
            self.title_label.setFont(self._title_font)

    def _update_glow_effect(self):
        if self._drag_over or self._hovered:
            blur_radius = 26
            color = QColor(255, 255, 255, 230)
        else:
            blur_radius = 0
            color = QColor(255, 255, 255, 0)
        self._glow_effect.setBlurRadius(blur_radius)
        self._glow_effect.setColor(color)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-pylog-curve"):
            self._drag_over = True
            self._update_title_font()
            self._update_glow_effect()
            self.update()
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-pylog-curve"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._drag_over = False
        self._update_title_font()
        self._update_glow_effect()
        self.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._drag_over = False
        self._update_title_font()
        self._update_glow_effect()
        self.update()
        if not event.mimeData().hasFormat("application/x-pylog-curve"):
            event.ignore()
            return
        raw_data = event.mimeData().data("application/x-pylog-curve").data().decode("utf-8")
        self.curves_dropped.emit(raw_data)
        event.acceptProposedAction()

    def enterEvent(self, event):
        self._hovered = True
        self._update_title_font()
        self._update_glow_effect()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._update_title_font()
        self._update_glow_effect()
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self._action_key)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(
            float(self._GLOW_PADDING + 1),
            float(self._GLOW_PADDING + 1),
            float(self._TILE_WIDTH - 2),
            float(self._TILE_HEIGHT - 2),
        )
        radius = self._TILE_RADIUS

        if self._drag_over or self._hovered:
            fill = QColor(255, 255, 255, 186)
            border = QColor(255, 255, 255, 255)
        else:
            fill = QColor(255, 255, 255, 86)
            border = QColor(255, 255, 255, 104)

        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        if radius <= 0:
            painter.drawRect(rect)
        else:
            painter.drawRoundedRect(rect, radius, radius)

        painter.setBrush(Qt.NoBrush)
        border_pen = QPen(border, 1.0)
        border_pen.setCosmetic(True)
        border_pen.setJoinStyle(Qt.RoundJoin)
        border_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(border_pen)
        if radius <= 0:
            painter.drawRect(rect)
        else:
            painter.drawRoundedRect(rect, radius, radius)


class WorkspaceLaunchpadWidget(QWidget):
    action_drop_requested = Signal(str, list)
    action_click_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground)
        self.setObjectName("workspaceLaunchpad")
        self._tiles = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        center = QWidget(self)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(18)
        center_layout.setAlignment(Qt.AlignCenter)
        self._center_layout = center_layout
        self.register_action(WorkspaceLaunchAction("plot", "Plot"))
        self.register_action(WorkspaceLaunchAction("data_viewer", "Data Viewer"))
        layout.addWidget(center, 1)

    def register_action(self, action):
        tile = WorkspaceLaunchTile(action.key, action.title)
        tile.curves_dropped.connect(lambda raw_data, key=action.key: self._handle_action_drop(key, raw_data))
        tile.clicked.connect(self.action_click_requested.emit)
        self._tiles[action.key] = tile
        self._center_layout.addWidget(tile, 0, Qt.AlignCenter)
        return tile

    def _handle_action_drop(self, action_key, raw_data):
        curves = parse_curve_mime_payload(raw_data)
        if curves:
            self.action_drop_requested.emit(action_key, curves)
