from PySide6.QtWidgets import QScrollBar, QAbstractScrollArea, QGraphicsOpacityEffect, QWidget
from PySide6.QtCore import Qt, QObject, QEvent, QTimer, QPropertyAnimation, QEasingCurve

def get_scrollbar_qss():
    from core.app_config import app_config
    handle_color = app_config.get_theme_color("scrollbar_handle")
    is_dark = app_config.get_theme_name() != "Light"
    
    border_alpha = 120 if is_dark else 30
    border_color = f"rgba(255, 255, 255, {border_alpha})" if is_dark else f"rgba(0, 0, 0, {border_alpha})"
    
    return f"""
        QScrollBar:vertical {{
            border: none;
            background: transparent;
            width: 14px;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: {handle_color};
            min-height: 20px;
            border-radius: 7px;
            border: 1px solid {border_color};
            margin: 2px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            height: 0px;
            background: none;
        }}
        
        QScrollBar:horizontal {{
            border: none;
            background: transparent;
            height: 14px;
            margin: 0px;
        }}
        QScrollBar::handle:horizontal {{
            background: {handle_color};
            min-width: 20px;
            border-radius: 7px;
            border: 1px solid {border_color};
            margin: 2px;
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            width: 0px;
            background: none;
        }}
    """

class FloatingScrollbarManager(QObject):
    """
    Manages floating, auto-hiding scrollbars for a QAbstractScrollArea (or similar).
    """
    def __init__(self, target_widget):
        super().__init__(target_widget)
        self.target = target_widget
        self.v_scrollbar = None
        self.h_scrollbar = None
        
        # Install event filter to handle resize and hover
        self.target.installEventFilter(self)
        
        # Opacity effect logic
        self.opacity_effect = QGraphicsOpacityEffect(self.target)
        self.opacity_effect.setOpacity(1.0) # Actually we apply opacity to scrollbars, not target
        
        # We need independent opacity for scrollbars
        self.start_opacity = 0.0
        self.end_opacity = 1.0
        self.fade_duration = 200
        
        self._setup_scrollbars()

    def _setup_scrollbars(self):
        # 1. Vertical
        if isinstance(self.target, QAbstractScrollArea):
            self.target.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.target.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            
            # Create Custom V Bar
            self.v_scrollbar = QScrollBar(Qt.Vertical, self.target)
            self.v_scrollbar.hide() # Initial
            
            # Opacity
            self.v_opacity = QGraphicsOpacityEffect(self.v_scrollbar)
            self.v_opacity.setOpacity(0.0)
            self.v_scrollbar.setGraphicsEffect(self.v_opacity)
            
            # Anim
            self.v_anim = QPropertyAnimation(self.v_opacity, b"opacity")
            self.v_anim.setDuration(self.fade_duration)
            self.v_anim.setEasingCurve(QEasingCurve.InOutQuad)
            
            # Sync
            orig_v = self.target.verticalScrollBar()
            orig_v.valueChanged.connect(self.v_scrollbar.setValue)
            orig_v.rangeChanged.connect(self._sync_v_range)
            self.v_scrollbar.valueChanged.connect(orig_v.setValue)
            
            # Initial Sync
            self._sync_v_range(orig_v.minimum(), orig_v.maximum())
            
            # 2. Horizontal
            self.h_scrollbar = QScrollBar(Qt.Horizontal, self.target)
            self.h_scrollbar.hide()
            
            # Initial theme
            self.update_theme()
            
            self.h_opacity = QGraphicsOpacityEffect(self.h_scrollbar)
            self.h_opacity.setOpacity(0.0)
            self.h_scrollbar.setGraphicsEffect(self.h_opacity)
            
            self.h_anim = QPropertyAnimation(self.h_opacity, b"opacity")
            self.h_anim.setDuration(self.fade_duration)
            self.h_anim.setEasingCurve(QEasingCurve.InOutQuad)
            
            orig_h = self.target.horizontalScrollBar()
            orig_h.valueChanged.connect(self.h_scrollbar.setValue)
            orig_h.rangeChanged.connect(self._sync_h_range)
            self.h_scrollbar.valueChanged.connect(orig_h.setValue)
            
            self._sync_h_range(orig_h.minimum(), orig_h.maximum())
            
            # Show them (they are hidden by opacity but widget must be visible)
            # self.v_scrollbar.show() # REMOVE: Let _sync handles visibility based on range
            # self.h_scrollbar.show()

    def update_theme(self):
        """Update floating scrollbar colors."""
        qss = get_scrollbar_qss()
        if self.v_scrollbar:
            self.v_scrollbar.setStyleSheet(qss)
        if self.h_scrollbar:
            self.h_scrollbar.setStyleSheet(qss)

    def _sync_v_range(self, min_val, max_val):
        self.v_scrollbar.setRange(min_val, max_val)
        self.v_scrollbar.setPageStep(self.target.verticalScrollBar().pageStep())
        
        # Auto-hide if not needed
        should_show = (max_val - min_val) > 0
        if should_show and not self.v_scrollbar.isVisible():
            self.v_scrollbar.show()
        elif not should_show and self.v_scrollbar.isVisible():
            self.v_scrollbar.hide()
            
        self._update_geometry()

    def _sync_h_range(self, min, max):
        self.h_scrollbar.setRange(min, max)
        self.h_scrollbar.setPageStep(self.target.horizontalScrollBar().pageStep())
        
        should_show = (max - min) > 0
        if should_show and not self.h_scrollbar.isVisible():
            self.h_scrollbar.show()
        elif not should_show and self.h_scrollbar.isVisible():
            self.h_scrollbar.hide()
            
        self._update_geometry()

    def _update_geometry(self):
        w = self.target.width()
        h = self.target.height()
        sb_w = 14
        
        if self.v_scrollbar:
            self.v_scrollbar.setGeometry(w - sb_w, 0, sb_w, h)
            self.v_scrollbar.raise_()
            
        if self.h_scrollbar:
            self.h_scrollbar.setGeometry(0, h - sb_w, w, sb_w)
            self.h_scrollbar.raise_()

    def eventFilter(self, watched, event):
        if watched == self.target:
            if event.type() == QEvent.Resize:
                self._update_geometry()
            elif event.type() == QEvent.Enter:
                self.fade_in()
            elif event.type() == QEvent.Leave:
                self.fade_out()
        return False

    def fade_in(self):
        if self.v_scrollbar:
            self.v_anim.stop()
            self.v_anim.setStartValue(self.v_opacity.opacity())
            self.v_anim.setEndValue(1.0)
            self.v_anim.start()
        if self.h_scrollbar:
            self.h_anim.stop()
            self.h_anim.setStartValue(self.h_opacity.opacity())
            self.h_anim.setEndValue(1.0)
            self.h_anim.start()

    def fade_out(self):
        if self.v_scrollbar:
            self.v_anim.stop()
            self.v_anim.setStartValue(self.v_opacity.opacity())
            self.v_anim.setEndValue(0.0)
            self.v_anim.start()
        if self.h_scrollbar:
            self.h_anim.stop()
            self.h_anim.setStartValue(self.h_opacity.opacity())
            self.h_anim.setEndValue(0.0)
            self.h_anim.start()
