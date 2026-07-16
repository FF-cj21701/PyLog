import os
from core.app_config import app_config
from PySide6.QtWidgets import (QDialog, QFormLayout, QSpinBox, QDoubleSpinBox, 
                               QComboBox, QFileDialog, QMessageBox, QGroupBox, 
                               QDialogButtonBox, QVBoxLayout, QApplication)
from PySide6.QtGui import (QPainter, QPdfWriter, QPageLayout, QPageSize, 
                          QPen, QFont, QImage, QColor, QClipboard)
from PySide6.QtCore import Qt, QRect, QRectF, QPointF, QSizeF, QMarginsF, QMimeData, QBuffer, QIODevice
from PySide6.QtSvg import QSvgGenerator
from ..ui.base_dialog import ThemeDialog


def _analysis_track_name(track, index):
    name = str(getattr(track, "track_name", "") or "").strip()
    if name:
        return name
    header = getattr(track, "header", None)
    items = getattr(header, "items", None) or []
    if items:
        item = items[0]
        return str(item.get("title") or item.get("name") or f"Track {index + 1}")
    return f"Track {index + 1}"


def _analysis_track_label(track, index):
    name = _analysis_track_name(track, index)
    curves = getattr(getattr(track, "plot_widget", None), "curves", None) or []
    image_curve = next((curve for curve in curves if curve.get("is_image")), None)
    if image_curve:
        info = image_curve.get("info", {})
        curve_name = str(info.get("title") or info.get("name") or "").strip()
        if curve_name and curve_name != name:
            return f"{name} / {curve_name}"
    return name


class PlotAnalysisRenderer:
    """Render selected, already configured plot tracks into an in-memory image."""

    def __init__(self, log_widget):
        self.log_widget = log_widget

    def render(
        self,
        track_names,
        depth_start,
        depth_end,
        width=1600,
        height=1200,
        *,
        include_depth_track=False,
        preserve_aspect=False,
        respect_current_vertical_scale=False,
    ):
        requested = list(dict.fromkeys(str(name).strip() for name in (track_names or []) if str(name).strip()))
        if not requested:
            raise ValueError("at least one analysis track is required")
        start, end = float(depth_start), float(depth_end)
        if start >= end:
            raise ValueError("depth_start must be less than depth_end")
        width, height = int(width), int(height)
        if width < 320 or height < 320:
            raise ValueError("analysis image width and height must be at least 320 pixels")

        available = []
        for index, track in enumerate(self.log_widget.track_containers):
            name = _analysis_track_name(track, index)
            label = _analysis_track_label(track, index)
            available.append((track, name, label, index))
        aliases = {
            alias: item
            for item in available
            for alias in (item[1], item[2])
        }
        missing = [name for name in requested if name not in aliases]
        if missing:
            raise ValueError(f"analysis track(s) not found: {', '.join(missing)}")

        selected_ids = {id(aliases[name][0]) for name in requested}
        auto_depth_names = []
        if include_depth_track:
            from ..rendering.plot_components import PainterDepthTrack

            depth_item = next(
                (item for item in available if isinstance(getattr(item[0], "plot_widget", None), PainterDepthTrack)),
                None,
            )
            if depth_item and id(depth_item[0]) not in selected_ids:
                selected_ids.add(id(depth_item[0]))
                auto_depth_names.append(depth_item[1])
        selected = [item for item in available if id(item[0]) in selected_ids]
        source_widths = [max(1, int(item[0].width())) for item in selected]
        total_source_width = sum(source_widths)
        source_header_height = 0
        for track, _name, _label, _index in selected:
            header = getattr(track, "header", None)
            if header is not None:
                if hasattr(header, "adjust_height"):
                    header.adjust_height()
                source_header_height = max(source_header_height, int(header.height()))
        source_heights = []
        for item in selected:
            height_getter = getattr(item[0], "height", None)
            source_heights.append(max(1, int(height_getter()))) if callable(height_getter) else None
        source_height = max(source_heights or [height])
        effective_source_height = float(source_height)
        current_visible_depth_range = None
        vertical_scale_applied = False
        if respect_current_vertical_scale:
            viewbox_getter = getattr(self.log_widget, "get_master_viewbox", None)
            viewbox = viewbox_getter() if callable(viewbox_getter) else None
            if viewbox is not None:
                try:
                    visible_start, visible_end = (float(value) for value in viewbox.viewRange()[1])
                    visible_span = abs(visible_end - visible_start)
                    requested_span = abs(end - start)
                    if visible_span > 0:
                        current_visible_depth_range = [visible_start, visible_end]
                        source_plot_height = max(1.0, float(source_height - source_header_height))
                        effective_source_height = source_header_height + source_plot_height * requested_span / visible_span
                        vertical_scale_applied = True
                except (AttributeError, IndexError, TypeError, ValueError):
                    pass
        requested_bounds = [width, height]
        if preserve_aspect:
            scale_to_bounds = min(width / total_source_width, height / effective_source_height)
            width = max(1, int(round(total_source_width * scale_to_bounds)))
            height = max(1, int(round(effective_source_height * scale_to_bounds)))
        track_widths = [max(1, int(round(width * value / total_source_width))) for value in source_widths]
        track_widths[-1] += width - sum(track_widths)
        scale_factor = width / total_source_width

        header_height = int(round(source_header_height * scale_factor))
        header_height = min(header_height, max(0, height - 160))

        image = QImage(width, height, QImage.Format_ARGB32)
        output_dpi = 96.0 * scale_factor
        dots_per_meter = int(round(output_dpi / 0.0254))
        image.setDotsPerMeterX(dots_per_meter)
        image.setDotsPerMeterY(dots_per_meter)
        image.fill(app_config.get_theme_qcolor("plot_bg"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        try:
            self._render_tracks(painter, selected, track_widths, start, end, width, height, header_height, scale_factor)
        finally:
            painter.end()

        tracks_metadata = []
        left = 0
        for (track, name, label, index), track_width in zip(selected, track_widths):
            curves = getattr(getattr(track, "plot_widget", None), "curves", None) or []
            curve_metadata = []
            for curve in curves:
                info = curve.get("info", {})
                curve_metadata.append({
                    "name": info.get("title") or info.get("name") or "Unknown",
                    "unit": info.get("unit", ""),
                    "minimum": info.get("min"),
                    "maximum": info.get("max"),
                    "is_image": bool(curve.get("is_image")),
                })
            tracks_metadata.append({
                "index": index,
                "name": name,
                "label": label,
                "is_image": any(curve["is_image"] for curve in curve_metadata),
                "is_depth": type(getattr(track, "plot_widget", None)).__name__ == "PainterDepthTrack",
                "pixel_left": left,
                "pixel_right": left + track_width,
                "pixel_width": track_width,
                "curves": curve_metadata,
            })
            left += track_width

        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        png_bytes = bytes(buffer.data())
        buffer.close()
        return {
            "image": image,
            "png_bytes": png_bytes,
            "metadata": {
                "width": width,
                "height": height,
                "source_width": total_source_width,
                "source_height": source_height,
                "effective_source_height": effective_source_height,
                "requested_bounds": requested_bounds,
                "preserve_aspect": bool(preserve_aspect),
                "respect_current_vertical_scale": bool(respect_current_vertical_scale),
                "vertical_scale_applied": vertical_scale_applied,
                "current_visible_depth_range": current_visible_depth_range,
                "render_scale": width / total_source_width,
                "output_dpi": output_dpi,
                "auto_included_depth_tracks": auto_depth_names,
                "header_height": header_height,
                "plot_top": header_height,
                "plot_bottom": height,
                "depth_start": start,
                "depth_end": end,
                "theme": app_config.get_theme_name(),
                "tracks": tracks_metadata,
            },
        }

    def _render_tracks(self, painter, selected, track_widths, start, end, width, height, header_height, scale_factor):
        from ..rendering.plot_components import PainterDepthTrack

        scale_control = getattr(self.log_widget, "scale_control", None)
        combo = getattr(scale_control, "combo", None)
        scale_text = combo.currentText() if combo is not None else None
        left = 0
        for (track, _name, _label, _index), track_width in zip(selected, track_widths):
            rect = QRect(left, 0, track_width, height)
            depth_scale = scale_text if isinstance(track.plot_widget, PainterDepthTrack) else None
            track.render_to(
                painter,
                rect,
                start,
                end,
                scale=scale_factor,
                scale_text=depth_scale,
                draw_border=False,
                header_h_override=header_height,
            )
            left += track_width

        pen_width = max(1.0, 1.2 * scale_factor)
        pen = QPen(app_config.get_theme_qcolor("track_divider"), pen_width)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        offset = pen_width / 2.0
        painter.drawLine(QPointF(offset, offset), QPointF(width - offset, offset))
        painter.drawLine(QPointF(offset, header_height), QPointF(width - offset, header_height))
        painter.drawLine(QPointF(offset, height - offset), QPointF(width - offset, height - offset))
        painter.drawLine(QPointF(offset, offset), QPointF(offset, height - offset))
        left = 0
        for track_width in track_widths:
            left += track_width
            x = width - offset if left == width else left
            painter.drawLine(QPointF(x, offset), QPointF(x, height - offset))



class LogExportDialog(ThemeDialog):
    def __init__(self, current_range, global_range, defined_range=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Settings")
        self.resize(380, 420)
        
        self.current_range = current_range
        self.global_range = global_range
        self.defined_range = defined_range
        self.copy_to_clipboard_requested = False
        
        main_layout = QVBoxLayout()
        self.setLayout(main_layout)
        
        # 1. Depth Range Group
        range_group = QGroupBox("Depth Range")
        range_layout = QFormLayout()
        range_group.setLayout(range_layout)
        
        self.range_mode = QComboBox()
        items = ["Current View", "Full Well"]
        if self.defined_range and self.defined_range[0] is not None and self.defined_range[1] is not None:
             items.append("Defined Range")
        items.append("Custom")
        self.range_mode.addItems(items)
        self.range_mode.currentTextChanged.connect(self.on_range_mode_changed)
        
        self.start_depth_spin = QDoubleSpinBox()
        self.start_depth_spin.setRange(-10000, 100000)
        self.start_depth_spin.setDecimals(2)
        
        self.end_depth_spin = QDoubleSpinBox()
        self.end_depth_spin.setRange(-10000, 100000)
        self.end_depth_spin.setDecimals(2)
        
        range_layout.addRow("Range Mode:", self.range_mode)
        range_layout.addRow("Start Depth:", self.start_depth_spin)
        range_layout.addRow("End Depth:", self.end_depth_spin)
        
        self.on_range_mode_changed("Current View") # Init state
        main_layout.addWidget(range_group)
        
        # 2. Output Settings Group
        output_group = QGroupBox("Output Settings")
        output_layout = QFormLayout()
        output_group.setLayout(output_layout)
        
        self.format_combo = QComboBox()
        self.format_combo.addItems(["PDF", "JPG"])
        self.format_combo.currentTextChanged.connect(self.on_format_changed)
        output_layout.addRow("Format:", self.format_combo)
        
        self.page_mode = QComboBox()
        self.page_mode.addItems([
            "Full Plot (Single Page)",
            "A0 (1189mm Height)",
            "A1 (841mm Height)",
            "A2 (594mm Height)",
            "A3 (420mm Height)",
            "A4 (297mm Height)"
        ])
        self.page_mode.setEnabled(True) # Default PDF
        output_layout.addRow("Page Mode:", self.page_mode)
        
        self.dpi_combo = QComboBox()
        self.dpi_combo.addItems(["96", "150", "300", "600"])
        self.dpi_combo.setCurrentText("96")
        output_layout.addRow("DPI:", self.dpi_combo)
        
        main_layout.addWidget(output_group)
        main_layout.addStretch()
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.copy_btn = buttons.addButton("Copy", QDialogButtonBox.ActionRole)
        self.copy_btn.clicked.connect(self.on_copy_clicked)
        
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)
        
    def on_copy_clicked(self):
        self.copy_to_clipboard_requested = True
        self.accept()
        
    def on_range_mode_changed(self, text):
        if text == "Current View":
            self.start_depth_spin.setValue(self.current_range[0])
            self.end_depth_spin.setValue(self.current_range[1])
            self.start_depth_spin.setEnabled(False)
            self.end_depth_spin.setEnabled(False)
        elif text == "Full Well":
            self.start_depth_spin.setValue(self.global_range[0])
            self.end_depth_spin.setValue(self.global_range[1])
            self.start_depth_spin.setEnabled(False)
            self.end_depth_spin.setEnabled(False)
        elif text == "Defined Range" and self.defined_range:
            self.start_depth_spin.setValue(self.defined_range[0])
            self.end_depth_spin.setValue(self.defined_range[1])
            self.start_depth_spin.setEnabled(False)
            self.end_depth_spin.setEnabled(False)
        else: # Custom
            self.start_depth_spin.setEnabled(True)
            self.end_depth_spin.setEnabled(True)
            
    def on_format_changed(self, text):
        # Multi-page only supported for PDF
        self.page_mode.setEnabled(text == "PDF")
        if text == "JPG":
            self.page_mode.setCurrentIndex(0)
            
    def get_settings(self):
        return {
            'range_mode': self.range_mode.currentText(),
            'start': self.start_depth_spin.value(),
            'end': self.end_depth_spin.value(),
            'format': self.format_combo.currentText(),
            'dpi': int(self.dpi_combo.currentText()),
            'page_mode': self.page_mode.currentText()
        }

class LogExporter:
    def __init__(self, log_widget):
        self.log_widget = log_widget

    def launch_export(self):
        """Launch the Advanced Export Dialog, compute scale, and execute export."""
        from ..rendering.plot_components import InteractivePlotWidget
        
        lw = self.log_widget
        if not lw.track_containers:
            QMessageBox.warning(lw, "Export", "No tracks to export.")
            return

        start_d, end_d = 0.0, 1000.0
        for track in lw.track_containers:
            if isinstance(track.plot_widget, InteractivePlotWidget):
                (_, (start_d, end_d)) = track.plot_widget.getViewBox().viewRange()
                break
        
        g_start = lw.global_min_depth or 0.0
        g_end = lw.global_max_depth or 1000.0
        
        defined = (lw.custom_min_depth, lw.custom_max_depth)
        
        dialog = LogExportDialog((start_d, end_d), (g_start, g_end), defined, lw)
        if dialog.exec() == QDialog.Accepted:
            settings = dialog.get_settings()
            
            curr_scale = 50
            if hasattr(lw, 'scale_control'):
                try:
                    text = lw.scale_control.combo.currentText()
                    curr_scale = int(text.split(':')[1])
                except:
                    vb = lw.get_master_viewbox()
                    if vb and lw.track_containers:
                        h_px = lw.track_containers[0].plot_widget.height()
                        (_, (min_y, max_y)) = vb.viewRange()
                        span = max_y - min_y
                        if span > 0 and h_px > 0:
                            dpi = lw.screen().physicalDotsPerInchY() if lw.screen() else 96.0
                            curr_scale = (39.3701 * dpi) / (h_px / span)
            
            settings['scale_val'] = curr_scale
            
            if dialog.copy_to_clipboard_requested:
                self.execute_clipboard_export(settings)
            else:
                self.execute_export(settings)
        else:
            win = lw.window()
            if win and hasattr(win, 'statusBar'):
                win.statusBar().clearMessage()
    
    def execute_clipboard_export(self, s):
        """Render to SVG (vector) + High-res QImage (fallback) and copy to clipboard."""
        from ..rendering.plot_components import PainterDepthTrack
        
        # High DPI for the raster fallback
        dpi = 300 
        scale_factor = dpi / 96.0
        
        units_span = s['end'] - s['start']
        h_cm = units_span * 100.0 / s['scale_val']
        h_data_px = int(h_cm / 2.54 * dpi)
        
        # Account for Header Height (Always included in export)
        max_header_h_px = 0
        for track in self.log_widget.track_containers:
            if hasattr(track, 'header'):
                track.header.adjust_height()
                max_header_h_px = max(max_header_h_px, int(track.header.height() * scale_factor))
        
        total_h_px = h_data_px + max_header_h_px
        track_widths = [int(track.width() * scale_factor) for track in self.log_widget.track_containers]
        total_w_px = sum(track_widths)
        
        # 1. Render to SVG (Vector)
        svg_buffer = QBuffer()
        svg_buffer.open(QIODevice.WriteOnly)
        
        generator = QSvgGenerator()
        generator.setOutputDevice(svg_buffer)
        generator.setResolution(dpi)
        generator.setViewBox(QRect(0, 0, total_w_px, total_h_px))
        generator.setTitle("PyLog Vector Export")
        
        with app_config.theme_context("Light"):
            painter_svg = QPainter(generator)
            painter_svg.setRenderHint(QPainter.Antialiasing)
            painter_svg.setRenderHint(QPainter.TextAntialiasing)
            painter_svg.setRenderHint(QPainter.SmoothPixmapTransform)
            self._render_tracks_to_painter(painter_svg, total_w_px, total_h_px, track_widths, s, scale_factor, max_header_h_px)
            painter_svg.end()
        
        # 2. Render to QImage (Raster) for standard clipboard compatibility
        image = QImage(total_w_px, total_h_px, QImage.Format_ARGB32)
        # Set resolution for raster image metadata
        dpm = int(dpi / 0.0254)
        image.setDotsPerMeterX(dpm); image.setDotsPerMeterY(dpm)
        image.fill(Qt.white)
        
        with app_config.theme_context("Light"):
            painter_img = QPainter(image)
            painter_img.setRenderHint(QPainter.Antialiasing)
            painter_img.setRenderHint(QPainter.TextAntialiasing)
            painter_img.setRenderHint(QPainter.SmoothPixmapTransform)
            self._render_tracks_to_painter(painter_img, total_w_px, total_h_px, track_widths, s, scale_factor, max_header_h_px)
            painter_img.end()
        
        svg_buffer.close()

        # 3. Populate Clipboard
        mime_data = QMimeData()
        mime_data.setData("image/svg+xml", svg_buffer.data())
        mime_data.setImageData(image)
        
        QApplication.clipboard().setMimeData(mime_data)
        
        win = self.log_widget.window()
        if win and hasattr(win, 'statusBar'):
            win.statusBar().showMessage("Vector plot copied to clipboard.", 5000)

    def _render_tracks_to_painter(self, painter, total_w, total_h, track_widths, s, scale_factor, max_header_h):
        """Utility to render tracks to any painter (SVG, Image, etc)."""
        from ..rendering.plot_components import PainterDepthTrack
        
        # 1. First Pass: Render all track content without internal borders
        curr_x = 0
        current_scale_str = self.log_widget.scale_control.combo.currentText()
        
        for i, track in enumerate(self.log_widget.track_containers):
            t_rect = QRect(curr_x, 0, track_widths[i], total_h)
            scale_txt = current_scale_str if isinstance(track.plot_widget, PainterDepthTrack) else None
            # [Refactor] Use consistent global header height for all tracks
            track.render_to(painter, t_rect, s['start'], s['end'], scale=scale_factor, scale_text=scale_txt, draw_border=False, header_h_override=max_header_h)
            curr_x += track_widths[i]

        # 2. Second Pass: Draw crisp vertical and horizontal separators on TOP
        curr_x = 0
        sep_color = app_config.get_theme_qcolor("track_divider")
        pen_w = 1.2 * scale_factor
        separator_pen = QPen(sep_color, pen_w)
        separator_pen.setCapStyle(Qt.FlatCap)
        painter.setPen(separator_pen)
        
        offset = pen_w / 2.0
        # Horizontal Divider should be at the global max header height
        
        # Define the structural box bounds
        x1, x2 = offset, total_w - offset
        y1, y2 = offset, total_h - offset
        
        # Horizontal lines (Top, Bottom, and Header-Plot separator)
        painter.drawLine(QPointF(x1, max_header_h), QPointF(x2, max_header_h))
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y1))
        painter.drawLine(QPointF(x1, y2), QPointF(x2, y2))
        
        curr_x = 0
        for i, tw in enumerate(track_widths):
            # Leftmost border
            if i == 0:
                painter.drawLine(QPointF(x1, y1), QPointF(x1, y2))
            
            curr_x += tw
            
            # Vertical separator logic
            if i == len(track_widths) - 1:
                # Rightmost border
                painter.drawLine(QPointF(x2, y1), QPointF(x2, y2))
            else:
                # Internal vertical separator
                painter.drawLine(QPointF(curr_x, y1), QPointF(curr_x, y2))

    def execute_export(self, s):
        """Coordinate high-res rendering to File/Printer."""
        from ..rendering.plot_components import PainterDepthTrack
        
        dpi = s['dpi']
        scale_factor = dpi / 96.0 
        
        units_span = s['end'] - s['start']
        # Physical height in cm for 1:S scale = span * 100 / S
        h_cm = units_span * 100.0 / s['scale_val']
        h_data_px = int(h_cm / 2.54 * dpi)
        
        # Account for Header Height (Always included in export)
        max_header_h_px = 0
        for track in self.log_widget.track_containers:
            if hasattr(track, 'header'):
                track.header.adjust_height()
                max_header_h_px = max(max_header_h_px, int(track.header.height() * scale_factor))
        
        total_h_px = h_data_px + max_header_h_px
        
        # Width: sum of current track widths * scale_factor
        track_widths = [int(t.width() * scale_factor) for t in self.log_widget.track_containers]
        total_w_px = sum(track_widths)
        
        if s['format'] == 'JPG':
            if total_h_px > 30000:
                 QMessageBox.warning(self.log_widget, "Limit", f"Total height too large ({total_h_px}px). Truncating.")
                 total_h_px = 30000
            
            with app_config.theme_context("Light"):
                image = QImage(total_w_px, total_h_px, QImage.Format_ARGB32)
                image.fill(Qt.white)
                
                # Set device resolution for metadata and QPainter awareness
                dpm = int(dpi / 0.0254)
                image.setDotsPerMeterX(dpm)
                image.setDotsPerMeterY(dpm)
                
                painter = QPainter(image)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setRenderHint(QPainter.TextAntialiasing)
                painter.setRenderHint(QPainter.SmoothPixmapTransform)
                
                # 1. First Pass: Render all track content without internal borders
                curr_x = 0
                current_scale_str = self.log_widget.scale_control.combo.currentText()
                
                for i, track in enumerate(self.log_widget.track_containers):
                    t_rect = QRect(curr_x, 0, track_widths[i], total_h_px)
                    # Pass scale text only to Depth Track
                    scale_txt = current_scale_str if isinstance(track.plot_widget, PainterDepthTrack) else None
                    # [Refactor] Use consistent global header height for all tracks
                    track.render_to(painter, t_rect, s['start'], s['end'], scale=scale_factor, scale_text=scale_txt, draw_border=False, header_h_override=max_header_h_px)
                    curr_x += track_widths[i]

                # 2. Second Pass: Draw crisp vertical and horizontal separators on TOP
                curr_x = 0
                sep_color = app_config.get_theme_qcolor("track_divider")
                pen_w = 1.2 * scale_factor
                separator_pen = QPen(sep_color, pen_w)
                separator_pen.setCapStyle(Qt.FlatCap)
                painter.setPen(separator_pen)
                
                offset = pen_w / 2.0
                
                # Define structural box bounds
                x1_px, x2_px = offset, total_w_px - offset
                y1_px, y2_px = offset, total_h_px - offset

                # Horizontal lines
                painter.drawLine(QPointF(x1_px, max_header_h_px), QPointF(x2_px, max_header_h_px))
                painter.drawLine(QPointF(x1_px, y1_px), QPointF(x2_px, y1_px))
                painter.drawLine(QPointF(x1_px, y2_px), QPointF(x2_px, y2_px))
                
                curr_x = 0
                for i, tw in enumerate(track_widths):
                    # Leftmost border
                    if i == 0:
                        painter.drawLine(QPointF(x1_px, y1_px), QPointF(x1_px, y2_px))
                    
                    curr_x += tw
                    
                    if i == len(track_widths) - 1:
                        # Rightmost border
                        painter.drawLine(QPointF(x2_px, y1_px), QPointF(x2_px, y2_px))
                    else:
                        # Internal vertical separator
                        painter.drawLine(QPointF(curr_x, y1_px), QPointF(curr_x, y2_px))
                    
                painter.end()
            
            path, _ = QFileDialog.getSaveFileName(self.log_widget, "Save JPG", "", "JPEG Files (*.jpg)")
            if path:
                image.save(path, "JPG", 95)
                QMessageBox.information(self.log_widget, "Success", f"Exported to {os.path.basename(path)}")
        else:
            path, _ = QFileDialog.getSaveFileName(self.log_widget, "Save PDF", "", "PDF Files (*.pdf)")
            if not path: return
            
            # --- [PDF Multi-page Logic] ---
            page_h_px = None # Default: single page
            if "A0" in s['page_mode']: page_h_px = int(1189.0 / 25.4 * dpi)
            elif "A1" in s['page_mode']: page_h_px = int(841.0 / 25.4 * dpi)
            elif "A2" in s['page_mode']: page_h_px = int(594.0 / 25.4 * dpi)
            elif "A3" in s['page_mode']: page_h_px = int(420.0 / 25.4 * dpi)
            elif "A4" in s['page_mode']: page_h_px = int(297.0 / 25.4 * dpi)
            
            # [PDF CHUNKED RENDERING] 
            # If total_h_px is extremely large (e.g. > 15000px), QPdfWriter/QPainter 
            # can fail or run out of memory when creating a single large page.
            # We enforce a chunked page-splitting if it exceeds this threshold.
            forced_paging = False
            if s['format'] == 'PDF' and not page_h_px and h_data_px > 15000:
                forced_paging = True
                # Use a large virtual page (e.g., 2 meters) to split the giant image
                page_h_px = int(2000.0 / 25.4 * dpi) 
                # Update UI/Status so user knows it's being split
                win = self.log_widget.window()
                if win and hasattr(win, 'statusBar'):
                    win.statusBar().showMessage("Large Plot detected: Splitting PDF into segments to prevent crash...", 5000)

            with app_config.theme_context("Light"):
                writer = QPdfWriter(path)
                writer.setResolution(dpi)
                
                # Margin settings
                h_margin_mm = 3.0  # Left/Right margin in mm
                v_margin_mm = 3.0  # Top (first page) / Bottom (last page) margin in mm
                
                # Paper dimensions
                pdf_page_h = page_h_px if page_h_px else total_h_px
                page_w_mm = total_w_px / dpi * 25.4 + 2 * h_margin_mm
                page_h_mm = pdf_page_h / dpi * 25.4
                
                if not page_h_px and not forced_paging:
                    # Single page: add top + bottom margins to page height
                    writer.setPageSize(QPageSize(QSizeF(page_w_mm, page_h_mm + 2 * v_margin_mm), QPageSize.Unit.Millimeter))
                    writer.setPageMargins(QMarginsF(h_margin_mm, v_margin_mm, h_margin_mm, v_margin_mm), QPageLayout.Unit.Millimeter)
                else:
                    # Multi-page: first page gets top margin only
                    writer.setPageSize(QPageSize(QSizeF(page_w_mm, page_h_mm + v_margin_mm), QPageSize.Unit.Millimeter))
                    writer.setPageMargins(QMarginsF(h_margin_mm, v_margin_mm, h_margin_mm, 0), QPageLayout.Unit.Millimeter)
                
                painter = QPainter(writer)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setRenderHint(QPainter.TextAntialiasing)
                painter.setRenderHint(QPainter.SmoothPixmapTransform)
                
                # [FIX] Get actual printable height for Page 1 (accounts for margins)
                printable_h_px = writer.height()
                
                current_scale_str = self.log_widget.scale_control.combo.currentText()
                # Resolve separator color from current theme context
                sep_color = app_config.get_theme_qcolor("track_divider")
                pen_w = 1.2 * scale_factor
                separator_pen = QPen(sep_color, pen_w)
                total_w = total_w_px

                if not page_h_px and not forced_paging:
                    # Single Page Mode (Existing)
                    curr_x = 0
                    for i, track in enumerate(self.log_widget.track_containers):
                        t_rect = QRect(curr_x, 0, track_widths[i], total_h_px)
                        scale_txt = current_scale_str if isinstance(track.plot_widget, PainterDepthTrack) else None
                        track.render_to(painter, t_rect, s['start'], s['end'], scale=scale_factor, scale_text=scale_txt)
                        painter.setPen(separator_pen)
                        if i == 0: painter.drawLine(curr_x, 0, curr_x, total_h_px)
                        curr_x += track_widths[i]
                        painter.drawLine(curr_x, 0, curr_x, total_h_px)
                else:
                    # Multi-page Mode
                    # Page 1: Header + Data (Use printable height)
                    # Page 2+: Data Only (Margins removed, so printable ~= full page)
                    
                    # Height available for data on page 1
                    available_data_h1 = printable_h_px - max_header_h_px
                    # Percentage of total data height that fits on page 1
                    ratio_p1 = available_data_h1 / h_data_px
                    depth_span = s['end'] - s['start']
                    depth_p1_end = s['start'] + (depth_span * ratio_p1)
                    
                    # Render Page 1
                    curr_x = 0
                    for i, track in enumerate(self.log_widget.track_containers):
                        # Use printable_h_px for rect height to match page 1 boundaries
                        # [Refactor] Use track_widths for exact X alignment
                        t_rect = QRect(curr_x, 0, track_widths[i], printable_h_px)
                        
                        scale_txt = current_scale_str if isinstance(track.plot_widget, PainterDepthTrack) else None
                        track.render_to(painter, t_rect, s['start'], depth_p1_end, scale=scale_factor, scale_text=scale_txt, draw_border=False, header_h_override=max_header_h_px)
                        curr_x += track_widths[i]

                    # 2. Draw separators for PDF Page 1 (Custom because of paging)
                    curr_x = 0
                    painter.setPen(separator_pen)
                    offset = pen_w / 2.0
                    x1, x2 = offset, total_w - offset
                    y1, y2 = offset, printable_h_px - offset 
                    
                    # Horizontal Divider
                    painter.drawLine(QPointF(x1, max_header_h_px), QPointF(x2, max_header_h_px))
                    painter.drawLine(QPointF(x1, y1), QPointF(x2, y1))
                    
                    curr_x = 0
                    for i, tw in enumerate(track_widths):
                        # Left/Right and internal borders
                        if i == 0: painter.drawLine(QPointF(x1, y1), QPointF(x1, y2))
                        curr_x += tw
                        if i == len(track_widths) - 1: painter.drawLine(QPointF(x2, y1), QPointF(x2, y2))
                        else: painter.drawLine(QPointF(curr_x, y1), QPointF(curr_x, y2))
                    
                    # Render Subsequent Pages
                    remaining_h = h_data_px - available_data_h1
                    curr_depth_start = depth_p1_end
                    
                    while remaining_h > 0:
                        is_last_page = remaining_h <= page_h_px
                        if is_last_page:
                            # Last page: add bottom margin
                            writer.setPageSize(QPageSize(QSizeF(page_w_mm, page_h_mm + v_margin_mm), QPageSize.Unit.Millimeter))
                            writer.setPageMargins(QMarginsF(h_margin_mm, 0, h_margin_mm, v_margin_mm), QPageLayout.Unit.Millimeter)
                        else:
                            # Middle pages: no top/bottom margins for seamless stitching
                            writer.setPageSize(QPageSize(QSizeF(page_w_mm, page_h_mm), QPageSize.Unit.Millimeter))
                            writer.setPageMargins(QMarginsF(h_margin_mm, 0, h_margin_mm, 0), QPageLayout.Unit.Millimeter)
                        writer.newPage()
                        
                        this_page_data_h = min(remaining_h, page_h_px)
                        this_ratio = this_page_data_h / h_data_px
                        curr_depth_end = curr_depth_start + (depth_span * this_ratio)
                        
                        curr_x = 0
                        for i, track in enumerate(self.log_widget.track_containers):
                            p_rect = QRect(curr_x, 0, track_widths[i], int(this_page_data_h))
                            track.plot_widget.render_to(painter, p_rect, curr_depth_start, curr_depth_end, scale=scale_factor, draw_border=False)
                            curr_x += track_widths[i]
                        
                        # Draw vertical separators with the SAME offsets as Page 1
                        painter.setPen(separator_pen)
                        offset = pen_w / 2.0
                        x1, x2 = offset, total_w - offset
                        y2 = int(this_page_data_h)
                        
                        curr_x = 0
                        for i, tw in enumerate(track_widths):
                            if i == 0: painter.drawLine(QPointF(x1, 0), QPointF(x1, y2))
                            curr_x += tw
                            if i == len(track_widths) - 1: painter.drawLine(QPointF(x2, 0), QPointF(x2, y2))
                            else: painter.drawLine(QPointF(curr_x, 0), QPointF(curr_x, y2))
                        
                        # Draw bottom border on the last page
                        if is_last_page:
                            painter.drawLine(QPointF(x1, y2), QPointF(x2, y2))

                        remaining_h -= page_h_px
                        curr_depth_start = curr_depth_end
                
                painter.end()
            QMessageBox.information(self.log_widget, "Success", f"Exported to {os.path.basename(path)}")
            
            # Clear status bar message if main window is available
            win = self.log_widget.window()
            if win and hasattr(win, 'statusBar'):
                win.statusBar().clearMessage()
