"""
FillManager - Handles complex fill logic for tracks, specifically 
Accumulative Fills (Stacked Area Charts) and synchronizing cross-fill chains.
"""
import numpy as np
from PySide6.QtGui import QColor, QBrush
from ..utils.plot_style_utils import normalize_fill_style


class FillManager:
    """Static class to decouple multi-curve stacking and filling logic."""

    @staticmethod
    def _display_data_for_item(data, info):
        """Return the x data expected by PlotCurveItem for the current axis mode."""
        if info.get('log', False):
            return np.log10(np.clip(data, 1e-10, None))
        return data

    @staticmethod
    def update_accumulative_fills(track_container, is_enabled):
        """
        Calculates stacked/log-stacked data for curves within a track.
        Handles data backup, interpolation/resampling to a common grid, 
        cumulative summation, and cross-fill configuration.
        """
        curves = [c for c in track_container.plot_widget.curves if not c.get('is_image')]
        if not curves:
            return

        if is_enabled:
            # 1. Store original states for restoration if not already present
            for c in curves:
                if '_orig_data' not in c:
                    c['_orig_data'] = c['data'].copy()
                if '_orig_depth' not in c:
                    # Backup depth as well for restoration
                    c['_orig_depth'] = c['depth'].copy() if hasattr(c['depth'], 'copy') else list(c['depth'])
                if '_orig_info' not in c:
                    # Backup info dict (contains original fill_mode etc)
                    c['_orig_info'] = c['info'].copy()

            # 2. Determine common depth grid from original data only.
            flat_depths = []
            max_native_pts = 0
            for c in curves:
                d = np.asarray(c.get('_orig_depth', c.get('depth', [])), dtype=float)
                d = d[np.isfinite(d)]
                if d.size > 0:
                    flat_depths.append(float(np.min(d)))
                    flat_depths.append(float(np.max(d)))
                    max_native_pts = max(max_native_pts, len(d))
            
            if not flat_depths: return
            
            d_min, d_max = min(flat_depths), max(flat_depths)
            if d_min > d_max: d_min, d_max = d_max, d_min

            # [FIX] Use adaptive resolution matching the highest density curve in the track
            # Fixed 0.1m step was too coarse (e.g. 1.6m span yielded only 16 pts).
            n_pts = max(500, min(100000, max_native_pts))
            common_depth = np.linspace(d_min, d_max, n_pts)

            accum_x = np.zeros(n_pts)
            stacked_values = []
            prev_curve_name = None
            prev_curve_entry = None
            
            for i, c in enumerate(curves):
                info = c['info']
                item = c['item']
                
                # Interpolate original data to common grid
                orig_data = c['_orig_data']
                orig_depth = c['_orig_depth']
                
                # Ensure data and depth are same length for interpolation
                n_base = min(len(orig_data), len(orig_depth))
                o_d = np.asarray(orig_data[:n_base], dtype=float)
                o_dp = np.asarray(orig_depth[:n_base], dtype=float)
                valid = np.isfinite(o_d) & np.isfinite(o_dp)
                if np.count_nonzero(valid) < 2:
                    grid_data = np.zeros_like(common_depth)
                else:
                    o_d, o_dp = o_d[valid], o_dp[valid]
                    idx_sort = np.argsort(o_dp)
                    o_d, o_dp = o_d[idx_sort], o_dp[idx_sort]
                    grid_data = np.interp(common_depth, o_dp, o_d, left=np.nan, right=np.nan)
                    grid_data = np.nan_to_num(grid_data, nan=0.0)
                
                # Stack
                accum_x += grid_data
                stacked_values.append(accum_x.copy())

            is_log_stack = any(c.get('info', {}).get('log', False) for c in curves)
            finite_segments = [v[np.isfinite(v)] for v in stacked_values if np.any(np.isfinite(v))]
            if finite_segments:
                finite_stacked = np.concatenate(finite_segments)
                if is_log_stack:
                    positive_stacked = finite_stacked[finite_stacked > 0]
                    if positive_stacked.size > 0:
                        common_min = max(1e-10, float(np.min(positive_stacked)))
                        common_max = max(common_min * 10.0, float(np.max(positive_stacked)))
                    else:
                        common_min, common_max = 1e-4, 1.0
                else:
                    common_min = min(0.0, float(np.min(finite_stacked)))
                    common_max = max(0.0, float(np.max(finite_stacked)))
            else:
                common_min, common_max = (1e-4, 1.0) if is_log_stack else (0.0, 1.0)
            if common_min == common_max:
                common_max = common_min * 10.0 if is_log_stack else common_min + 1.0
            baseline_value = common_min if is_log_stack else 0.0

            for i, c in enumerate(curves):
                info = c['info']
                item = c['item']
                accum_curve = stacked_values[i]
                if is_log_stack:
                    accum_curve = np.where(
                        np.isfinite(accum_curve) & (accum_curve > 0),
                        accum_curve,
                        baseline_value,
                    )
                
                # Update item data (in-place modification of curve object)
                c['data'] = accum_curve.copy()
                c['depth'] = common_depth
                
                # Keep plot_data in raw data space. ScrollManager applies log10 on slices.
                c['plot_data'] = c['data']
                c.pop('_last_slice', None)

                info['min'] = common_min
                info['max'] = common_max
                
                # Configure Stacking/Chaining Fills
                if i == 0:
                    info['fill_mode'] = 'Left'
                    c['_accum_fill_target_curve'] = None
                    c['_accum_fill_baseline'] = baseline_value
                else:
                    info['fill_mode'] = prev_curve_name
                    c['_accum_fill_target_curve'] = prev_curve_entry
                    c.pop('_accum_fill_baseline', None)
                
                prev_curve_name = info.get('name')
                prev_curve_entry = c
                
                # Apply settings immediately via track_container's existing method
                # This ensures the new fill_mode is applied to the UI/items
                full_idx = -1
                for idx, full_c in enumerate(track_container.plot_widget.curves):
                    if full_c is c:
                        full_idx = idx
                        break
                if full_idx != -1:
                    track_container.apply_curve_settings(full_idx, info, trigger_others=False)
                    info = c['info']
                    c['plot_data'] = c['data']
                    c.pop('_last_slice', None)
                    item.setData(FillManager._display_data_for_item(c['data'], info), common_depth)
                    if i == 0 and hasattr(item, 'curve') and hasattr(item.curve, 'setFillTargetData'):
                        fill_style = normalize_fill_style(info)
                        baseline = np.full_like(common_depth, baseline_value, dtype=float)
                        item.curve.setFillTargetData(
                            QBrush(QColor(fill_style['fill_color'])),
                            baseline,
                            common_depth,
                            common_min,
                            common_max,
                            info.get('log', False),
                            info.get('invert_x', False),
                            common_min,
                            common_max,
                            info.get('log', False),
                            info.get('invert_x', False),
                        )

        else:
            # RESTORE Original Independent Data
            FillManager.apply_track_data_reset(track_container)

        track_container.header.update()

    @staticmethod
    def apply_cross_fill(track_container, curve_idx):
        """
        Logical helper to configure the 'Fill to Curve' (Cross-Fill) behavior.
        Finds the target curve by name and updates the source curve's painter path parameters.
        """
        curves = track_container.plot_widget.curves
        if curve_idx >= len(curves): return
        
        c_entry = curves[curve_idx]
        if c_entry.get('is_image'): return
        
        info = c_entry['info']
        item = c_entry.get('item', c_entry.get('curve'))
        fill_mode = info.get('fill_mode', 'None')
        
        # [FIX] Do NOT clear target data if it's a standard Left/Right/None fill.
        # CurveManager.update_line_on_item already handles standard fill setup/clearing.
        # Interference here was causing Left/Right fills to be wiped out.
        if fill_mode in ['None', 'Left', 'Right'] or not hasattr(item, 'curve'):
            return

        # Handle "Fill to [Curve Name]"
        target_curve = c_entry.get('_accum_fill_target_curve')
        if target_curve not in curves:
            target_curve = next((c for c in curves if c.get('info', {}).get('name') == fill_mode), None)
        if target_curve and hasattr(item.curve, 'setFillTargetData'):
            t_info = target_curve['info']
            fill_style = normalize_fill_style(info)
            brush = QBrush(QColor(fill_style['fill_color']))
            
            item.curve.setFillTargetData(
                brush, 
                target_curve['data'], target_curve['depth'],
                t_info.get('min', 0), t_info.get('max', 100), t_info.get('log', False), t_info.get('invert_x', False),
                info.get('min', 0), info.get('max', 100), info.get('log', False), info.get('invert_x', False)
            )

    @staticmethod
    def apply_track_data_reset(track_container):
        """Restores all curves to their original non-accumulated state."""
        curves = [c for c in track_container.plot_widget.curves if not c.get('is_image')]
        for c in curves:
            if '_orig_data' in c:
                c['data'] = c['_orig_data']
                del c['_orig_data']
            if '_orig_depth' in c:
                c['depth'] = c['_orig_depth']
                del c['_orig_depth']
            if '_orig_info' in c:
                c['info'].update(c['_orig_info'])
                del c['_orig_info']
            c.pop('_accum_fill_target_curve', None)
            c.pop('_accum_fill_baseline', None)
            c.pop('_last_slice', None)
            
            idx = track_container.plot_widget.curves.index(c)
            track_container.apply_curve_settings(idx, c['info'], trigger_others=False)
