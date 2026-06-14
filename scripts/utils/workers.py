import numpy as np
from collections import OrderedDict
from PySide6.QtCore import QObject, Signal, QRunnable
from .colormap_utils import get_standard_colormap
from .curve_loading import load_curve_bundle_for_plot
from .logger import logger
from .plot_style_utils import DEFAULT_IMAGE_CMAP, DEFAULT_NULL_COLOR
from core.app_config import app_config

MAX_LUT_CACHE = 3
LUT_CACHE = OrderedDict()

def get_cached_lut(cmap_name, invert, null_color):
    # Resolve Auto/White/Black FIRST, then use in key
    res = app_config.resolve_null_color(null_color)
    theme_ctx = app_config.get_theme_name() if res == 'Theme' else 'Static'
    key = (cmap_name, bool(invert), res, theme_ctx)
    if key in LUT_CACHE:
        LUT_CACHE.move_to_end(key)
        return LUT_CACHE[key]
    else:
        pg_cmap, _ = get_standard_colormap(cmap_name, invert=invert)
        lut = pg_cmap.getLookupTable(0.0, 1.0, 255, alpha=True, mode='byte')
        # Use the already resolved 'res' color
        if res == 'Theme':
            bg_qcolor = app_config.get_theme_qcolor('plot_bg')
            nc = [bg_qcolor.red(), bg_qcolor.green(), bg_qcolor.blue(), 255]
        elif res == 'Transparent':
            nc = [0, 0, 0, 0]
        elif res == 'White':
            nc = [255, 255, 255, 255]
        else: # Black or other
            nc = [0, 0, 0, 255]
        
        LUT_CACHE[key] = np.vstack([lut, np.array([nc], dtype=np.ubyte)])
        if len(LUT_CACHE) > MAX_LUT_CACHE:
            LUT_CACHE.popitem(last=False)
        return LUT_CACHE[key]

class WorkerSignals(QObject):
    """Signals for the DataFetchWorker."""
    finished = Signal(object, object, dict, object, int, int, object) # data, depth, info, context (track), well_id, curve_id, rgb_full
    error = Signal(str)

class ImageSliceSignals(QObject):
    """Signals for the ImageSliceWorker."""
    # indexed_slice, lut, actual_min, actual_max, track, v_step, tile_index
    ready = Signal(object, object, float, float, object, int, int)
    error = Signal(str)

def _emit_signal_safe(signals_obj, signal_name, *args) -> bool:
    """
    Safely emit a Qt signal.
    Returns False when source QObject is already deleted (common during UI teardown).
    """
    try:
        signal = getattr(signals_obj, signal_name)
        signal.emit(*args)
        return True
    except RuntimeError as e:
        msg = str(e)
        deleted_markers = (
            "Signal source has been deleted",
            "Internal C++ object",
            "already deleted",
            "has been deleted",
        )
        if any(marker in msg for marker in deleted_markers):
            logger.warning(f"[WORKER_DEBUG] Skip emit '{signal_name}': {msg}")
            return False
        raise

class ImageSliceWorker(QRunnable):
    """Worker to perform image slicing and processing in background."""
    def __init__(self, track, min_y, max_y, buffer_y, cache, v_step=1, track_w_px=0, tile_index=-1):
        super().__init__()
        self.track = track
        self.min_y = min_y
        self.max_y = max_y
        self.buffer_y = buffer_y
        self.cache = cache
        self.v_step = v_step
        self.track_w_px = int(track_w_px) if track_w_px else 0
        self.tile_index = tile_index
        # Capture current info to avoid main-thread mutation issues
        # [FIX] Find the actual image curve info, not just curves[0]
        image_curve = next((c for c in getattr(track.plot_widget, 'curves', []) if c.get('is_image')), {})
        self.info = image_curve.get('info', {}).copy()
        self.render_generation = cache.get('render_generation', 0)
        self.signals = ImageSliceSignals()

    def run(self):
        try:
            # Handle asymmetric buffers (top, bottom)
            if isinstance(self.buffer_y, (list, tuple)):
                b_top, b_bottom = self.buffer_y
            else:
                b_top = b_bottom = self.buffer_y

            # Calculate New Buffer Range
            new_min = self.min_y - b_top
            new_max = self.max_y + b_bottom
            
            # Clamp to well limits
            f_min, f_max = self.cache['full_depth_range']
            new_min = max(f_min, new_min)
            new_max = min(f_max, new_max)
            
            # 1. Fetch RAW data slice
            depth_arr = self.cache['depth']
            raw_data = self.cache['data']
            
            # Binary search for row indices
            start_idx = np.searchsorted(depth_arr, new_min)
            end_idx = np.searchsorted(depth_arr, new_max)
            
            if start_idx >= end_idx:
                _emit_signal_safe(self.signals, 'ready', None, None, 0, 0, self.track, self.v_step, self.tile_index)
                return

            # [OPTIMIZATION] Adaptive horizontal downsampling
            source_cols = raw_data.shape[1]
            h_step = max(1, source_cols // self.track_w_px) if self.track_w_px > 0 and source_cols > (self.track_w_px * 2) else 1
                
            # Extraction of raw slice with vertical downsampling
            # Use slice directly to avoid a copy where possible
            data_slice = raw_data[start_idx : end_idx : self.v_step, ::h_step]

            # [INFO] Worker slice stats
            if data_slice is not None:
                try:
                    d_min_raw = np.nanmin(data_slice) if data_slice.size > 0 else "N/A"
                    d_max_raw = np.nanmax(data_slice) if data_slice.size > 0 else "N/A"
                    logger.debug(f"[WORKER_DEBUG] Slice {start_idx}:{end_idx}, Shape {data_slice.shape}, Range [{d_min_raw}, {d_max_raw}]")
                except Exception as e:
                    logger.warning(f"[WORKER_DEBUG] Stats failed: {e}")


            
            # 2. Re-indexing (Normalization) based on current info
            info = self.info
            is_log = info.get('log', False)
            c_min = info.get('min', 0.0)
            c_max = info.get('max', 100.0)
            
            # [ANTI-LOOP] Ensure c_max > c_min effectively
            if not is_log and abs(c_max - c_min) < 1e-9:
                c_max = c_min + 1.0
                
            # [OPTIMIZATION] Unified Null Handling
            invalid_mask = ~np.isfinite(data_slice)
                
            if is_log:
                working_slice = data_slice.astype(float)
                pos_mask = (working_slice > 0)
                invalid_mask |= (~pos_mask)
                working_slice[~pos_mask] = 1e-4
                
                temp_min = max(1e-4, c_min)
                temp_max = max(temp_min * 10, c_max)
                l_min, l_max = np.log10(temp_min), np.log10(temp_max)
                norm = np.clip((np.log10(working_slice) - l_min) / (l_max - l_min) * 254, 0, 254)
            else:
                # [FIX] Precision Normalization to [0, 254]
                norm = np.clip((data_slice - c_min) / (c_max - c_min) * 254, 0, 254)
            
            # [FIX] Handle NaN values before casting to uint8
            # We use 255 as the "Null Color" index (Theme/White/Transparent)
            norm_filled = np.nan_to_num(norm, nan=255.0)
            indexed_slice = norm_filled.astype(np.uint8)
            indexed_slice[invalid_mask] = 255
            
            cmap_name = info.get('cmap', DEFAULT_IMAGE_CMAP).lower()
            invert = info.get('invert', False)
            null_color = info.get('null_color', DEFAULT_NULL_COLOR)
            full_lut = get_cached_lut(cmap_name, invert, null_color)
            
            # [FIX] Resilient mapping: Find valid boundaries to handle leading/mid-data NaNs
            actual_min = depth_arr[start_idx]
            if np.isnan(actual_min):
                # Fallback to linear extrapolation from first valid or index-based fallback
                valid_idx = np.where(~np.isnan(depth_arr))[0]
                if valid_idx.size > 0:
                    v_start, v_end = valid_idx[0], valid_idx[-1]
                    # Estimate based on avg sample interval
                    step = (depth_arr[v_end] - depth_arr[v_start]) / (v_end - v_start) if v_end != v_start else 0.125
                    actual_min = depth_arr[v_start] - (v_start - start_idx) * step
                else:
                    actual_min = start_idx * 0.125 # True absolute fallback
            
            # [FIX] Precise Boundary Calculation
            if end_idx < len(depth_arr):
                actual_max = depth_arr[end_idx]
                if np.isnan(actual_max):
                    actual_max = actual_min + (end_idx - start_idx) * 0.125
            else:
                # Handle end of array by extrapolating one sample interval
                interval = (depth_arr[-1] - depth_arr[0]) / (len(depth_arr) - 1) if (len(depth_arr) > 1 and np.isfinite(depth_arr[0]) and np.isfinite(depth_arr[-1])) else 0.125
                actual_max = depth_arr[-1] + interval
            
            # Emit results
            _emit_signal_safe(
                self.signals, 'ready',
                indexed_slice, full_lut, actual_min, actual_max, self.track, self.v_step, self.tile_index
            )
            
        except Exception as e:
            if not _emit_signal_safe(self.signals, 'error', str(e)):
                logger.warning(f"[WORKER_DEBUG] ImageSliceWorker suppressed error emit: {e}")

class DataFetchWorker(QRunnable):
    """Worker to fetch curve data from database using QThreadPool and local connections."""
    def __init__(self, db_path, well_id, curve_id, context=None, preferences=None):
        super().__init__()
        self.db_path = db_path
        self.well_id = well_id
        self.curve_id = curve_id
        self.context = context
        self.preferences = preferences or {} # [NEW] Pass UI preferences (cmap, null_color)
        self.signals = WorkerSignals()

    def run(self):
        try:
            result = load_curve_bundle_for_plot(
                self.db_path,
                self.well_id,
                self.curve_id,
                preferences=self.preferences,
            )
            if not result.get("ok"):
                _emit_signal_safe(self.signals, 'error', result.get("error", "Curve loading failed."))
                return

            _emit_signal_safe(
                self.signals,
                'finished',
                result["data"],
                result["depth"],
                result["info"],
                self.context,
                self.well_id,
                self.curve_id,
                result.get("rgb_full"),
            )
            
        except Exception as e:
            if not _emit_signal_safe(self.signals, 'error', str(e)):
                logger.warning(f"[WORKER_DEBUG] DataFetchWorker suppressed error emit: {e}")

