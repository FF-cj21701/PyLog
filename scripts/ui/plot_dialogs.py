import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QGroupBox, QFormLayout, QLineEdit, 
                               QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox, QPushButton, 
                               QDialogButtonBox, QFontComboBox, QColorDialog, QGridLayout,
                               QWidget, QStackedWidget, QListWidget, QListWidgetItem, QLabel, QScrollArea,
                               QStyle, QProgressBar)
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QFont, QColor, QPainter, QLinearGradient, QBrush
from ..utils.colormap_utils import get_standard_colormap
from ..utils.plot_style_utils import (
    DEFAULT_FILL_COLOR,
    DEFAULT_IMAGE_CMAP,
    DEFAULT_NULL_COLOR,
    LEGACY_DEFAULT_FILL_COLOR,
    normalize_curve_plot_style,
    normalize_fill_style,
    resolve_auto_fill_color,
)
from ..utils.plot_value_utils import compute_auto_display_range
from ..rendering.plot_components import PainterDepthTrack
from core.app_config import app_config
from .base_dialog import ThemeDialog

# --- Curve Settings Modular Components ---

class BaseCurveSettingsWidget(QWidget):
    """Shared UI components for all curve types."""
    def __init__(self, info, curve_entry, parent=None):
        super().__init__(parent)
        self.info = info
        self.curve_entry = curve_entry
        self.setup_ui()

    def setup_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(15)

        # 1. Basic Info
        basic_group = QGroupBox("Basic Info")
        basic_layout = QFormLayout(basic_group)
        basic_layout.setLabelAlignment(Qt.AlignRight)
        # [DECOUPLE] Use 'Title' for display, 'Name' remains internal
        self.name_edit = QLineEdit(); basic_layout.addRow("Title:", self.name_edit)
        self.unit_edit = QLineEdit(); basic_layout.addRow("Unit:", self.unit_edit)
        self.layout.addWidget(basic_group)

        # 2. Font (Common Appearance)
        font_group = QGroupBox("Font Settings")
        font_layout = QFormLayout(font_group)
        font_layout.setLabelAlignment(Qt.AlignRight)
        self.font_combo = QFontComboBox(); font_layout.addRow("Font:", self.font_combo)
        self.font_size_spin = QSpinBox(); self.font_size_spin.setRange(6, 24)
        font_layout.addRow("Font Size:", self.font_size_spin)
        self.layout.addWidget(font_group)

        # 3. Type-Specific Placeholder for derived classes
        self.specific_group = QGroupBox("Appearance")
        self.specific_layout = QFormLayout(self.specific_group)
        self.specific_layout.setLabelAlignment(Qt.AlignRight)
        self.setup_specific_ui()
        self.layout.addWidget(self.specific_group)

        # 4. Scale & Range
        range_group = QGroupBox("Scale & Range")
        range_layout = QFormLayout(range_group)
        range_layout.setLabelAlignment(Qt.AlignRight)
        self.scale_combo = QComboBox(); self.scale_combo.addItems(["Linear", "Logarithmic"])
        range_layout.addRow("Scale Type:", self.scale_combo)
        self.min_spin = QDoubleSpinBox(); self.min_spin.setRange(-999999, 999999); self.min_spin.setDecimals(4)
        range_layout.addRow("Min Value:", self.min_spin)
        self.max_spin = QDoubleSpinBox(); self.max_spin.setRange(-999999, 999999); self.max_spin.setDecimals(4)
        range_layout.addRow("Max Value:", self.max_spin)
        self.range_visible_chk = QCheckBox(); range_layout.addRow("Show Range:", self.range_visible_chk)
        self.auto_btn = QPushButton("Auto Scale from Data"); self.auto_btn.clicked.connect(self.auto_scale)
        range_layout.addRow("", self.auto_btn)
        self.layout.addWidget(range_group)

        # Add stretch to push everything to the top
        self.layout.addStretch()

    def setup_specific_ui(self):
        """Override in subclasses."""
        pass

    def load_settings(self, info):
        self.info = info
        # [DECOUPLE] Prioritize title for display
        self.name_edit.setText(info.get('title', info.get('name', '')))
        self.unit_edit.setText(info.get('unit', ''))
        self.font_combo.setCurrentFont(QFont(info.get('font_family', 'Arial')))
        self.font_size_spin.setValue(info.get('font_size', 10))
        self.scale_combo.setCurrentIndex(1 if info.get('log', False) else 0)
        self.min_spin.setValue(info.get('min', 0))
        self.max_spin.setValue(info.get('max', 100))
        self.range_visible_chk.setChecked(info.get('range_visible', True))

    def get_settings(self):
        return {
            'title': self.name_edit.text(), # Save UI changes to 'title'
            'unit': self.unit_edit.text(),
            'font_family': self.font_combo.currentFont().family(),
            'font_size': self.font_size_spin.value(),
            'min': self.min_spin.value(),
            'max': self.max_spin.value(),
            'log': self.scale_combo.currentText() == "Logarithmic",
            'range_visible': self.range_visible_chk.isChecked(),
            'visible': True
        }

    def auto_scale(self):
        data = self.curve_entry.get('data')
        if data is None: return
        
        # [OPTIMIZATION] Check for Proxy + Cached Min/Max to avoid full-scans
        if hasattr(data, 'min') and hasattr(data, 'max'):
            d_min, d_max = data.min(), data.max()
            self.min_spin.setValue(float(d_min))
            self.max_spin.setValue(float(d_max))
            return

        if len(data) == 0: return
        is_log = (self.scale_combo.currentText() == "Logarithmic")
        d_min, d_max = compute_auto_display_range(data, is_log=is_log)
        # Use exact values without padding
        self.min_spin.setValue(d_min); self.max_spin.setValue(d_max)

class LineCurveSettingsWidget(BaseCurveSettingsWidget):
    """Settings for 1D line curves."""
    def setup_specific_ui(self):
        self.color_btn = QPushButton()
        self.current_color = QColor('#000000')
        self.color_btn.clicked.connect(self.choose_color)
        self.specific_layout.addRow("Color:", self.color_btn)
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0.5, 10); self.width_spin.setDecimals(1)
        self.specific_layout.addRow("Line Width:", self.width_spin)
        
        # 添加线型选择
        self.style_combo = QComboBox()
        self.style_combo.addItems(["Solid", "Dash", "Dot", "Dash Dot"])
        self.style_combo.setItemData(0, int(Qt.SolidLine.value))
        self.style_combo.setItemData(1, int(Qt.DashLine.value))
        self.style_combo.setItemData(2, int(Qt.DotLine.value))
        self.style_combo.setItemData(3, int(Qt.DashDotLine.value))
        self.specific_layout.addRow("Line Style:", self.style_combo)

        # Fill Settings
        self.fill_target_combo = QComboBox()
        self.fill_target_combo.addItems(["None", "Left", "Right"])
        self.specific_layout.addRow("Fill To:", self.fill_target_combo)

        self.fill_color_btn = QPushButton()
        self.current_fill_color = QColor(DEFAULT_FILL_COLOR)
        self.fill_color_auto = True
        self.fill_color_btn.clicked.connect(self.choose_fill_color)
        self.specific_layout.addRow("Fill Color:", self.fill_color_btn)

        self.fill_alpha_spin = QDoubleSpinBox()
        self.fill_alpha_spin.setRange(0.0, 1.0)
        self.fill_alpha_spin.setSingleStep(0.1)
        self.fill_alpha_spin.setDecimals(2)
        self.fill_alpha_spin.setValue(1.0)
        self.specific_layout.addRow("Fill Alpha (0-1):", self.fill_alpha_spin)

        # [NEW] Invert Axis Feature
        from PySide6.QtWidgets import QCheckBox
        self.invert_check = QCheckBox("Invert Axis (e.g. 100-0)")
        self.specific_layout.addRow("Display:", self.invert_check)

    def choose_color(self):
        color = QColorDialog.getColor(self.current_color, self)
        if color.isValid():
            self.current_color = color
            self.color_btn.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #888; border-radius: 4px;")
            if self.fill_color_auto:
                self.current_fill_color = QColor(resolve_auto_fill_color(color.name(), self.fill_alpha_spin.value()))
                self._update_fill_color_button()

    def choose_fill_color(self):
        color = QColorDialog.getColor(self.current_fill_color, self)
        if color.isValid():
            self.fill_color_auto = False
            self.current_fill_color = QColor(color.red(), color.green(), color.blue(), int(self.fill_alpha_spin.value() * 255))
            self._update_fill_color_button()

    def _is_auto_fill_color(self, info):
        if info.get('fill_color_auto') is not None:
            return bool(info.get('fill_color_auto'))
        fill_color_name = info.get('fill_color')
        if not fill_color_name or str(fill_color_name).lower() == LEGACY_DEFAULT_FILL_COLOR:
            return True
        fill_color = QColor(fill_color_name)
        line_color = QColor(info.get('color', '#000000'))
        auto_color = QColor(resolve_auto_fill_color(line_color.name(), fill_color.alpha() / 255.0))
        return (
            fill_color.isValid()
            and line_color.isValid()
            and (
                (
                    fill_color.red() == line_color.red()
                    and fill_color.green() == line_color.green()
                    and fill_color.blue() == line_color.blue()
                )
                or (
                    auto_color.isValid()
                    and fill_color.red() == auto_color.red()
                    and fill_color.green() == auto_color.green()
                    and fill_color.blue() == auto_color.blue()
                )
            )
        )

    def _update_fill_color_button(self):
        color = QColor(self.current_fill_color.red(), self.current_fill_color.green(), self.current_fill_color.blue())
        self.fill_color_btn.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #888; border-radius: 4px;")

    def load_settings(self, info, curve_names=None, is_accum_restricted=False):
        super().load_settings(info)
        self.current_color = QColor(info.get('color', '#000000'))
        self.color_btn.setStyleSheet(f"background-color: {self.current_color.name()}; border: 1px solid #888; border-radius: 4px;")
        self.width_spin.setValue(info.get('line_width', 1.0))
        
        # 加载线型设置
        try:
            raw_ls = info.get('line_style', Qt.SolidLine)
            ls_val = int(raw_ls.value) if hasattr(raw_ls, 'value') else int(raw_ls)
        except:
            ls_val = int(Qt.SolidLine.value)

        if ls_val == int(Qt.DashLine.value):
            self.style_combo.setCurrentIndex(1)
        elif ls_val == int(Qt.DotLine.value):
            self.style_combo.setCurrentIndex(2)
        elif ls_val == int(Qt.DashDotLine.value):
            self.style_combo.setCurrentIndex(3)
        else:
            self.style_combo.setCurrentIndex(0)

        # Load fill settings
        self.fill_target_combo.clear()
        self.fill_target_combo.addItems(["None", "Left", "Right"])
        if curve_names:
            self.fill_target_combo.addItems(curve_names)
            
        fill_mode = info.get('fill_mode', 'None')
        self.fill_target_combo.setCurrentText(fill_mode)
        
        # [NEW] Handle Accumulative Fill Restriction
        if is_accum_restricted:
            self.fill_target_combo.setEnabled(False)
            self.fill_target_combo.setToolTip("Managed by Accumulative Fill")
            # Create a label to show it's managed if needed, but disabling is clearer
        else:
            self.fill_target_combo.setEnabled(True)
            self.fill_target_combo.setToolTip("")
        
        self.fill_color_auto = self._is_auto_fill_color(info)
        fill_info = {**info, 'fill_color': None} if self.fill_color_auto else info
        fill_style = normalize_fill_style(fill_info)
        self.current_fill_color = QColor(fill_style['fill_color'])
            
        self._update_fill_color_button()
        self.fill_alpha_spin.setValue(fill_style['fill_alpha'])
        
        # [NEW] Load Invert Axis
        self.invert_check.setChecked(info.get('invert_x', False))

    def get_settings(self):
        s = super().get_settings()
        s.update({
            'color': self.current_color.name(), 
            'line_width': self.width_spin.value(),
            'line_style': int(self.style_combo.currentData()),
            'fill_mode': self.fill_target_combo.currentText(),
            'fill_color': None if self.fill_color_auto else QColor(self.current_fill_color.red(), self.current_fill_color.green(), self.current_fill_color.blue(), int(self.fill_alpha_spin.value() * 255)).name(QColor.HexArgb),
            'fill_color_auto': self.fill_color_auto,
            'fill_alpha': self.fill_alpha_spin.value(),
            'invert_x': self.invert_check.isChecked()
        })
        return s

class ColormapPreviewWidget(QWidget):
    """Simple widget to display a colormap preview."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(30)
        self.setFixedHeight(30)
        self.gradient = None

    def set_gradient(self, gradient):
        self.gradient = gradient
        self.update()

    def paintEvent(self, event):
        if not self.gradient:
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw gradient
        rect = self.rect()
        self.gradient.setStart(0, 0)
        self.gradient.setFinalStop(rect.width(), 0)
        
        painter.setBrush(QBrush(self.gradient))
        painter.setPen(Qt.NoPen)
        painter.drawRect(rect)
        
        # Optional: Add border
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QColor("#CCCCCC"))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))

class ImageCurveSettingsWidget(BaseCurveSettingsWidget):
    """Settings for 2D image curves."""
    def setup_specific_ui(self):
        self.cmap_combo = QComboBox()
        self.cmap_combo.addItems(["Thermal", "Heated", "BWR", "Bone", "Terrain", "Gray", "Viridis", "Plasma", "Inferno", "Magma"])
        self.specific_layout.addRow("Colormap:", self.cmap_combo)
        
        # [NEW] Preview Widget
        self.preview = ColormapPreviewWidget()
        self.specific_layout.addRow("Preview:", self.preview)
        
        self.invert_check = QCheckBox("Invert Colormap")
        self.specific_layout.addRow("", self.invert_check)
        
        self.null_color_combo = QComboBox()
        self.null_color_combo.addItems(['Auto', 'White', 'Black'])
        self.null_color_combo.currentTextChanged.connect(self.update_preview)
        
        # Connect to update preview
        self.cmap_combo.currentTextChanged.connect(self.update_preview)
        self.invert_check.toggled.connect(self.update_preview)

    def update_preview(self):
        cmap_name = self.cmap_combo.currentText()
        invert = self.invert_check.isChecked()
        _, grad = get_standard_colormap(cmap_name, invert=invert)
        self.preview.set_gradient(grad)

    def load_settings(self, info, curve_names=None, is_accum_restricted=False):
        normalized = normalize_curve_plot_style({**info, "is_image": True})
        super().load_settings(normalized)
        self.cmap_combo.setCurrentText(normalized.get('cmap', DEFAULT_IMAGE_CMAP).capitalize())
        self.invert_check.setChecked(normalized.get('invert', False))
        self.null_color_combo.setCurrentText(normalized.get('null_color', DEFAULT_NULL_COLOR))
        self.update_preview()

    def get_settings(self):
        s = super().get_settings()
        s.update({
            'cmap': self.cmap_combo.currentText(),
            'invert': self.invert_check.isChecked(),
            'null_color': self.null_color_combo.currentText()
        })
        return s

class BaseTrackSettingsWidget(QWidget):
    """Shared UI components for all track types (Width, Grid, Depth Range)."""
    def __init__(self, container, parent=None):
        super().__init__(parent)
        self.container = container
        self.plot = container.plot_widget if container else None
        self.setup_ui()

    def setup_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(15)

        # 1. Dimensions
        dim_group = QGroupBox("Dimensions")
        dim_layout = QFormLayout(dim_group)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(50, 2000)
        dim_layout.addRow("Track Width:", self.width_spin)
        self.track_name_edit = QLineEdit()
        dim_layout.addRow("Track Name:", self.track_name_edit)
        self.layout.addWidget(dim_group)

        # 2. Grid & Scale
        self.grid_group = QGroupBox("Grid & Scale")
        grid_layout = QFormLayout(self.grid_group)
        self.grid_x_chk = QCheckBox()
        self.grid_y_chk = QCheckBox()
        self.log_chk = QComboBox(); self.log_chk.addItems(["Linear", "Logarithmic"])
        grid_layout.addRow("Show Vertical Grid:", self.grid_x_chk)
        grid_layout.addRow("Show Horizontal Grid:", self.grid_y_chk)
        grid_layout.addRow("Scale Type:", self.log_chk)
        self.layout.addWidget(self.grid_group)
        

        # 3. Type-Specific Placeholder for derived classes
        self.specific_container = QWidget()
        self.specific_layout = QVBoxLayout(self.specific_container)
        self.specific_layout.setContentsMargins(0, 0, 0, 0)
        self.setup_specific_ui()
        self.layout.addWidget(self.specific_container)

        # 4. Depth Range
        depth_group = QGroupBox("Depth Range")
        depth_layout = QFormLayout(depth_group)
        self.d_start_spin = QDoubleSpinBox()
        self.d_end_spin = QDoubleSpinBox()
        for s in [self.d_start_spin, self.d_end_spin]:
            s.setRange(-9999, 99999); s.setDecimals(2)
        depth_layout.addRow("Depth Start:", self.d_start_spin)
        depth_layout.addRow("Depth End:", self.d_end_spin)
        
        # [NEW] Full Well Reset Button
        self.full_well_btn = QPushButton("Full Well")
        self.full_well_btn.clicked.connect(self.on_full_well_clicked)
        depth_layout.addRow("", self.full_well_btn)
        
        self.layout.addWidget(depth_group)

        # Add stretch to push everything to the top
        self.layout.addStretch()

    def setup_specific_ui(self): pass

    def on_full_well_clicked(self):
        """Fetch global well depth range from LogWidget and update spins."""
        log_w = self.container.find_log_widget() if self.container else None
        if log_w and log_w.global_min_depth is not None and log_w.global_max_depth is not None:
            self.d_start_spin.setValue(log_w.global_min_depth)
            self.d_end_spin.setValue(log_w.global_max_depth)

    def load_settings(self):
        if not self.container: return
        self.width_spin.setValue(int(self.container.width()))
        self.track_name_edit.setText(self.container.track_name or "")
        is_depth_track = isinstance(self.plot, PainterDepthTrack)
        self.grid_x_chk.setChecked(getattr(self.plot, 'show_grid_x', True)); self.grid_x_chk.setEnabled(not is_depth_track)
        self.grid_y_chk.setChecked(getattr(self.plot, 'show_grid_y', True)); self.grid_y_chk.setEnabled(not is_depth_track)
        self.log_chk.setCurrentIndex(1 if getattr(self.plot, 'is_log_scale', False) else 0); self.log_chk.setEnabled(not is_depth_track)
        
        # [FIX] Prefer model-defined scales over transient viewport magnification
        self.current_min, self.current_max = 0, 100
        if not is_depth_track and hasattr(self.plot, 'curves') and len(self.plot.curves) > 0:
            # [FIX] Prioritize finding the image curve for range info
            image_curve = next((c for c in self.plot.curves if c.get('is_image')), self.plot.curves[0])
            c0_info = image_curve['info']
            self.current_min = c0_info.get('min', 0)
            self.current_max = c0_info.get('max', 100)
        elif not is_depth_track and hasattr(self.plot, 'getPlotItem'):
            (xr_min, xr_max) = self.plot.getPlotItem().viewRange()[0]
            if getattr(self.plot, 'is_log_scale', False): self.current_min, self.current_max = 10**xr_min, 10**xr_max
            else: self.current_min, self.current_max = xr_min, xr_max
        
        log_w = self.container.find_log_widget()
        if log_w:
            # [FIX] Load actual depth limits (custom or global) instead of current viewport range
            d1 = log_w.custom_min_depth if log_w.custom_min_depth is not None else log_w.global_min_depth
            d2 = log_w.custom_max_depth if log_w.custom_max_depth is not None else log_w.global_max_depth
            
            if d1 is not None and d2 is not None:
                self.d_start_spin.setValue(d1)
                self.d_end_spin.setValue(d2)

    def get_settings(self):
        return {
            "name": self.track_name_edit.text(),
            "width": self.width_spin.value(),
            "grid_x": self.grid_x_chk.isChecked(),
            "grid_y": self.grid_y_chk.isChecked(),
            "log": self.log_chk.currentText() == "Logarithmic",
            "depth_start": self.d_start_spin.value(),
            "depth_end": self.d_end_spin.value(),
            "min": getattr(self, 'current_min', 0),
            "max": getattr(self, 'current_max', 360)
        }

class LineTrackSettingsWidget(BaseTrackSettingsWidget):
    """Settings for standard Curve tracks (Min/Max Axis)."""
    def setup_specific_ui(self):
        range_group = QGroupBox("Default Axis Range")
        range_layout = QFormLayout(range_group)
        self.min_spin = QDoubleSpinBox(); self.max_spin = QDoubleSpinBox()
        for s in [self.min_spin, self.max_spin]: s.setRange(-999999, 999999); s.setDecimals(4)
        range_layout.addRow("Axis Min:", self.min_spin)
        range_layout.addRow("Axis Max:", self.max_spin)
        self.auto_btn = QPushButton("Auto Scale from Data"); self.auto_btn.clicked.connect(self.auto_scale)
        range_layout.addRow("", self.auto_btn)
        self.specific_layout.addWidget(range_group)

        # Accumultive Fill Setting
        fill_group = QGroupBox("Fill Options")
        fill_layout = QFormLayout(fill_group)
        self.accum_fill_chk = QCheckBox("Accumulative Fill")
        fill_layout.addRow("", self.accum_fill_chk)
        self.specific_layout.addWidget(fill_group)

        self.log_chk.currentIndexChanged.connect(self.on_log_change)

    def load_settings(self):
        super().load_settings()
        is_depth_track = isinstance(self.plot, PainterDepthTrack)
        
        cur_min, cur_max = 0, 100
        if not is_depth_track and hasattr(self.plot, 'curves') and len(self.plot.curves) > 0:
            image_curve = next((c for c in self.plot.curves if c.get('is_image')), self.plot.curves[0])
            c0_info = image_curve['info']
            cur_min = c0_info.get('min', 0)
            cur_max = c0_info.get('max', 100)
        elif not is_depth_track and hasattr(self.plot, 'getPlotItem'):
            (min_x, max_x) = self.plot.getPlotItem().viewRange()[0]
            if getattr(self.plot, 'is_log_scale', False): cur_min, cur_max = 10**min_x, 10**max_x
            else: cur_min, cur_max = min_x, max_x
            
        self.min_spin.setValue(cur_min); self.min_spin.setEnabled(not is_depth_track)
        self.max_spin.setValue(cur_max); self.max_spin.setEnabled(not is_depth_track)

        # Load Accumulative Fill
        self.accum_fill_chk.setChecked(getattr(self.container, 'is_accum_fill', False))

    def get_settings(self):
        s = super().get_settings()
        s.update({
            "min": self.min_spin.value(), 
            "max": self.max_spin.value(),
            "is_accum_fill": self.accum_fill_chk.isChecked()
        })
        return s

    def on_log_change(self):
        if self.log_chk.currentText() == "Logarithmic" and self.min_spin.value() <= 0: self.min_spin.setValue(0.2)

    def auto_scale(self):
        if not self.container: return
        curves = self.container.plot_widget.curves
        if not curves: return
        
        is_log = (self.log_chk.currentText() == "Logarithmic")
        all_mins, all_maxs = [], []
        
        for c in curves:
            data = c['data']
            if data is None: continue
            
            if hasattr(data, 'min') and hasattr(data, 'max'):
                all_mins.append(data.min())
                all_maxs.append(data.max())
                continue

            d_min, d_max = compute_auto_display_range(data, is_log=is_log)
            all_mins.append(d_min)
            all_maxs.append(d_max)
                
        if not all_mins: return
        
        d_min = float(np.min(all_mins))
        d_max = float(np.max(all_maxs))
        self.min_spin.setValue(d_min); self.max_spin.setValue(d_max)

class ImageTrackSettingsWidget(BaseTrackSettingsWidget):
    """Settings for Imaging tracks (Color scale, Null color)."""
    def setup_specific_ui(self):
        self.grid_group.hide()
        
        # [RESTORED] Track-level background color for imaging tracks
        bg_group = QGroupBox("Track Background")
        bg_layout = QFormLayout(bg_group)
        self.null_color_combo = QComboBox()
        self.null_color_combo.addItems(["Auto", "White", "Black"])
        bg_layout.addRow("Background Color:", self.null_color_combo)
        self.specific_layout.addWidget(bg_group)

    def load_settings(self):
        super().load_settings()
        if hasattr(self.plot, 'curves') and self.plot.curves:
             # Sync with the first image curve's null_color for consistency
             img_c = next((c for c in self.plot.curves if c.get('is_image')), self.plot.curves[0])
             self.null_color_combo.setCurrentText(img_c.get('info', {}).get('null_color', DEFAULT_NULL_COLOR))

    def get_settings(self):
        s = super().get_settings()
        s.update({
             "null_color": self.null_color_combo.currentText()
        })
        return s

class DepthTrackSettingsWidget(BaseTrackSettingsWidget):
    """Settings specifically for Depth tracks (Header Title/Unit/Font)."""
    def setup_specific_ui(self):
        # Remove Grid & Scale options as they don't apply to depth axis labels in the same way
        self.grid_group.hide()
        
        header_group = QGroupBox("Header Appearance")
        header_layout = QFormLayout(header_group)
        header_layout.setLabelAlignment(Qt.AlignRight)
        
        self.unit_edit = QLineEdit()
        header_layout.addRow("Unit:", self.unit_edit)
        
        self.font_combo = QFontComboBox()
        header_layout.addRow("Font:", self.font_combo)
        
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(6, 24)
        header_layout.addRow("Font Size:", self.font_size_spin)
        
        self.specific_layout.addWidget(header_group)

        # [NEW] Depth Label Font controls
        label_group = QGroupBox("Depth Label Appearance")
        label_layout = QFormLayout(label_group)
        label_layout.setLabelAlignment(Qt.AlignRight)
        
        self.label_font_combo = QFontComboBox()
        label_layout.addRow("Label Font:", self.label_font_combo)
        
        self.label_font_size_spin = QSpinBox()
        self.label_font_size_spin.setRange(0, 24)
        self.label_font_size_spin.setSpecialValueText("Auto")
        label_layout.addRow("Label Font Size:", self.label_font_size_spin)
        
        # [NEW] Depth Masking controls
        self.mask_enabled_chk = QCheckBox("Enable Depth Masking (e.g. XX12)")
        label_layout.addRow("", self.mask_enabled_chk)
        
        self.mask_length_spin = QSpinBox()
        self.mask_length_spin.setRange(1, 10)
        label_layout.addRow("Masked Digits:", self.mask_length_spin)
        
        self.specific_layout.addWidget(label_group)

    def load_settings(self):
        super().load_settings()
        if hasattr(self.container, 'header'):
            self.unit_edit.setText(getattr(self.container.header, 'unit', 'm'))
            # Depth track header usually has its settings in the first item
            info = self.container.header.items[0] if self.container.header.items else {}
            self.font_combo.setCurrentFont(QFont(info.get('font_family', 'Arial')))
            self.font_size_spin.setValue(info.get('font_size', 10))
        else:
            self.unit_edit.setText("m")
            self.font_size_spin.setValue(10)
            
        # [NEW] Load Depth Label settings from plot_widget (PainterDepthTrack)
        if self.plot:
            self.label_font_combo.setCurrentFont(QFont(getattr(self.plot, 'label_font_family', 'Arial')))
            self.label_font_size_spin.setValue(getattr(self.plot, 'label_font_size', 0))
            self.mask_enabled_chk.setChecked(getattr(self.plot, 'label_mask_enabled', False))
            self.mask_length_spin.setValue(getattr(self.plot, 'label_mask_length', 2))

    def get_settings(self):
        s = super().get_settings()
        s.update({
            "unit": self.unit_edit.text(),
            "font_family": self.font_combo.currentFont().family(),
            "font_size": self.font_size_spin.value(),
            "label_font_family": self.label_font_combo.currentFont().family(),
            "label_font_size": self.label_font_size_spin.value(),
            "label_mask_enabled": self.mask_enabled_chk.isChecked(),
            "label_mask_length": self.mask_length_spin.value()
        })
        return s

class UnifiedSettingsDialog(ThemeDialog):
    """Unified host for both Curve and Track settings. Supports multi-type Hot-Swapping."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(450, 750)
        self.setMinimumSize(350, 600)
        self.apply_callback = None
        
        main_layout = QVBoxLayout()
        self.setLayout(main_layout)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QScrollArea.NoFrame)
        self.content_stack = QStackedWidget()
        self.scroll_area.setWidget(self.content_stack)
        main_layout.addWidget(self.scroll_area)

        # Pre-instantiate widgets to ensure smooth stacks
        self.line_curve_w = LineCurveSettingsWidget({}, {})
        self.image_curve_w = ImageCurveSettingsWidget({}, {})
        self.line_track_w = LineTrackSettingsWidget(None) # container=None initially
        self.image_track_w = ImageTrackSettingsWidget(None)
        self.depth_track_w = DepthTrackSettingsWidget(None)
        
        for w in [self.line_curve_w, self.image_curve_w, self.line_track_w, self.image_track_w, self.depth_track_w]:
            self.content_stack.addWidget(w)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self.on_apply)
        main_layout.addWidget(buttons)
        
        self.active_widget = None

    def load_for_curve(self, container, idx, apply_callback=None):
        """Transition into Curve Settings mode."""
        if self.active_widget and self.apply_callback:
            self.on_apply()
        self.apply_callback = apply_callback
        curve_entry = None
        if hasattr(container.plot_widget, 'curves') and idx < len(container.plot_widget.curves):
            curve_entry = container.plot_widget.curves[idx]
        if not curve_entry and idx < len(container.header.items):
             curve_entry = {'viewbox': None, 'curve': None, 'info': container.header.items[idx]}
        if not curve_entry: return

        info = curve_entry['info']
        is_image = info.get('is_image', False)
        self.setWindowTitle(f"Curve Settings: {info.get('name', 'Curve')}")
        
        if is_image:
            widget = self.image_curve_w
        else:
            widget = self.line_curve_w
        self.active_widget = widget
        
        other_curves = []
        if not is_image and hasattr(container.plot_widget, 'curves'):
            for i, c in enumerate(container.plot_widget.curves):
                if i != idx and not c.get('is_image'):
                    name = c.get('info', {}).get('name', f'Curve {i+1}')
                    other_curves.append(name)

        self.content_stack.setCurrentWidget(widget)
        widget.curve_entry = curve_entry
        
        is_accum_restricted = getattr(container, 'is_accum_fill', False)
        
        if is_image:
            widget.load_settings(info)
        else:
            widget.load_settings(info, curve_names=other_curves, is_accum_restricted=is_accum_restricted)

    def load_for_track(self, container, apply_callback=None):
        """Transition into Track Settings mode."""
        if self.active_widget and self.apply_callback:
            self.on_apply()
        self.apply_callback = apply_callback
        is_image_track = any(c.get('is_image') for c in container.plot_widget.curves)
        
        track_name = container.track_name
        if not track_name:
            if hasattr(container, 'header') and container.header.items:
                h_item = container.header.items[0]
                track_name = h_item.get('title') or h_item.get('name') or "Track"
            else:
                track_name = "Track"
            
        self.setWindowTitle(f"Track Settings: {track_name}")
        
        is_depth_track = hasattr(container, 'plot_widget') and isinstance(container.plot_widget, PainterDepthTrack)
        
        if is_depth_track:
            self.active_widget = self.depth_track_w
        else:
            self.active_widget = self.image_track_w if is_image_track else self.line_track_w
            
        self.content_stack.setCurrentWidget(self.active_widget)
        
        self.active_widget.container = container
        self.active_widget.plot = container.plot_widget
        self.active_widget.load_settings()

    def get_settings(self):
        return self.active_widget.get_settings() if self.active_widget else {}

    def on_apply(self):
        settings = self.get_settings()
        if self.apply_callback:
            self.apply_callback(settings)
            
        if "name" in settings:
            new_name = settings["name"]
            if not new_name and hasattr(self.active_widget, 'container'):
                container = self.active_widget.container
                if hasattr(container, 'header') and container.header.items:
                    h_item = container.header.items[0]
                    new_name = h_item.get('title') or h_item.get('name') or "Track"
                else:
                    new_name = "Track"
            
            if "Track Settings" in self.windowTitle():
                 self.setWindowTitle(f"Track Settings: {new_name}")
            elif "Curve Settings" in self.windowTitle():
                 self.setWindowTitle(f"Curve Settings: {new_name}")

    def open_for_curve(self, container, idx):
        curve_entry = None
        if hasattr(container.plot_widget, 'curves') and idx < len(container.plot_widget.curves):
            curve_entry = container.plot_widget.curves[idx]
        if not curve_entry: return

        def apply_cb(s): container.apply_curve_settings(idx, s)
        try: self.accepted.disconnect()
        except RuntimeError: pass
        self.accepted.connect(lambda: apply_cb(self.get_settings()))
        self.load_for_curve(container, idx, apply_callback=apply_cb)

    def load_settings(self, container, apply_callback=None):
        self.load_for_track(container, apply_callback)


class WellSelectionDialog(ThemeDialog):
    def __init__(self, wells, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Target Well")
        self.resize(450, 500)
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        header = QLabel("Apply Template")
        header.setStyleSheet(f"font-size: 18pt; font-weight: bold; color: {app_config.get_theme_color('primary')};")
        layout.addWidget(header)
        
        sub_header = QLabel("Choose a well to apply the visual template settings.")
        sub_header.setStyleSheet(f"color: {app_config.get_theme_color('text_dim')}; font-size: 10pt;")
        sub_header.setWordWrap(True)
        layout.addWidget(sub_header)
        
        layout.addWidget(QLabel("<b>Available Wells:</b>"))
        
        self.list_widget = QListWidget()
        self.list_widget.setSpacing(2)
        
        import os
        for well in wells:
            db_name = os.path.basename(well['db_path'])
            display_name = well['name']
            
            item = QListWidgetItem()
            item_text = f"{display_name}\nDatabase: {db_name}"
            item.setText(item_text)
            
            item.setIcon(self.style().standardIcon(QStyle.SP_FileIcon))
            item.setData(Qt.UserRole, well)
            item.setToolTip(f"Full Path: {well['db_path']}")
            self.list_widget.addItem(item)
        
        layout.addWidget(self.list_widget)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.list_widget.itemDoubleClicked.connect(self.accept)

    def get_selected_well(self):
        item = self.list_widget.currentItem()
        return item.data(Qt.UserRole) if item else None

class UnitEditDialog(ThemeDialog):
    def __init__(self, curve_name, current_unit, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Unit")
        self.resize(320, 140)
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        
        info = QLabel(f"Curve: <b>{curve_name}</b>")
        info.setWordWrap(True)
        info.setStyleSheet("color: #444;")
        layout.addWidget(info)
        
        form = QFormLayout()
        self.unit_edit = QLineEdit(current_unit)
        self.unit_edit.setPlaceholderText("e.g. m, ohm.m, v/v")
        form.addRow("New Unit:", self.unit_edit)
        layout.addLayout(form)
        
        self.unit_edit.selectAll()
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
    def get_unit(self):
        return self.unit_edit.text().strip()
