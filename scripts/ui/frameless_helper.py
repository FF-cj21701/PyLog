from PySide6.QtCore import QObject, Qt, QPoint, QRect, QEvent
from PySide6.QtWidgets import QWidget

class FramelessHelper(QObject):
    """
    Adds manual resizing support to frameless windows.
    Tracks mouse movement near borders and updates window geometry.
    """
    def __init__(self, target: QWidget, border_width=8):
        super().__init__(target)
        self.target = target
        self.border_width = border_width
        self.target.setMouseTracking(True)
        self.target.installEventFilter(self)
        
        self._dragging_edge = None # None, 'L', 'R', 'T', 'B', 'TL', 'TR', 'BL', 'BR'
        self._press_pos = QPoint()
        self._start_geometry = QRect()

    def _get_edge(self, pos: QPoint):
        """Determine which edge/corner the mouse is over."""
        w = self.target.width()
        h = self.target.height()
        bw = self.border_width
        
        left = pos.x() <= bw
        right = pos.x() >= w - bw
        top = pos.y() <= bw
        bottom = pos.y() >= h - bw
        
        if top and left: return 'TL'
        if top and right: return 'TR'
        if bottom and left: return 'BL'
        if bottom and right: return 'BR'
        if top: return 'T'
        if bottom: return 'B'
        if left: return 'L'
        if right: return 'R'
        return None

    def add_widget(self, widget: QWidget):
        """Monitor top-level containers to catch events that would otherwise be blocked."""
        if widget is None:
            return
        widget.setMouseTracking(True)
        widget.installEventFilter(self)
        # RECURSIVE REMOVED: Monitoring every child was the cause of UI lag.
        # Event bubbling handles most cases, and top-level monitoring is enough.

    def eventFilter(self, obj, event):
        etype = event.type()
        
        # 1. Early-out for non-mouse events
        if etype not in (QEvent.HoverMove, QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.MouseButtonRelease):
            return False

        # 2. Performance: Only process if we are near borders or already dragging
        # This prevents mapFromGlobal on every move in the dialog center.
        if not self._dragging_edge and etype in (QEvent.MouseMove, QEvent.HoverMove):
            # Optimization: Quick boundary check using local coordinates if possible
            # or global mapping only when necessary.
            pass

        try:
            # globalPosition() is more consistent across high-DPI screens
            g_pos = event.globalPosition().toPoint()
            local_pos = self.target.mapFromGlobal(g_pos)
        except AttributeError:
            return False

        if etype == QEvent.HoverMove:
            edge = self._get_edge(local_pos)
            self._update_cursor(edge)
            return False

        if etype == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                edge = self._get_edge(local_pos)
                if edge:
                    self._dragging_edge = edge
                    self._press_pos = g_pos
                    self._start_geometry = self.target.geometry()
                    return True
        
        if etype == QEvent.MouseMove:
            if self._dragging_edge:
                self._handle_resize(g_pos)
                return True
            else:
                # Still check for cursor update, but _get_edge is fast
                edge = self._get_edge(local_pos)
                self._update_cursor(edge)

        if etype == QEvent.MouseButtonRelease:
            if self._dragging_edge:
                self._dragging_edge = None
                self._update_cursor(None)
                return True # Consumed
            self._update_cursor(None)

        return False

    def _update_cursor(self, edge):
        if edge in ('TL', 'BR'): self.target.setCursor(Qt.SizeFDiagCursor)
        elif edge in ('TR', 'BL'): self.target.setCursor(Qt.SizeBDiagCursor)
        elif edge in ('T', 'B'): self.target.setCursor(Qt.SizeVerCursor)
        elif edge in ('L', 'R'): self.target.setCursor(Qt.SizeHorCursor)
        else: self.target.setCursor(Qt.ArrowCursor)

    def _handle_resize(self, global_pos: QPoint):
        diff = global_pos - self._press_pos
        rect = QRect(self._start_geometry)
        
        if 'L' in self._dragging_edge:
            rect.setLeft(rect.left() + diff.x())
        elif 'R' in self._dragging_edge:
            rect.setRight(self._start_geometry.right() + diff.x())
            
        if 'T' in self._dragging_edge:
            rect.setTop(rect.top() + diff.y())
        elif 'B' in self._dragging_edge:
            rect.setBottom(self._start_geometry.bottom() + diff.y())
        
        # Enforce minimum size
        if rect.width() >= self.target.minimumSize().width() and rect.height() >= self.target.minimumSize().height():
            self.target.setGeometry(rect)
