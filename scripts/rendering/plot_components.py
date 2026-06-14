# Re-exporting modules to maintain backward compatibility after Phase 5 split.
from .plot_constants import AXIS_WIDTH
from .graphics_items import get_physical_grid_steps, CachedGridItem, VerticalLoggingCurveItem
from .track_widgets import PainterDepthTrack, InteractivePlotWidget
from .overlays import HeaderWidget, SelectionOverlay

__all__ = [
    'AXIS_WIDTH',
    'get_physical_grid_steps',
    'CachedGridItem',
    'VerticalLoggingCurveItem',
    'PainterDepthTrack',
    'InteractivePlotWidget',
    'HeaderWidget',
    'SelectionOverlay'
]
