import pyqtgraph as pg
import numpy as np
from PySide6.QtGui import QLinearGradient, QColor

def get_standard_colormap(name="thermal", invert=False, n_levels=None):
    """
    Returns a tuple of (pyqtgraph.ColorMap, QLinearGradient) for a given name.
    Supports 'thermal', 'heated', 'bwr', 'bone', 'terrain', 'gray' and generic pg maps.
    If invert is True, reverses the colormap.
    If n_levels is an integer, quantizes the map into discrete bands.
    """
    name = str(name).lower()
    
    # 1. Define Stops and Colors
    if name == "gray" or name == "grayscale":
        pos = np.array([0.0, 1.0])
        colors = np.array([[0,0,0,255], [255,255,255,255]], dtype=np.ubyte)
        
    elif name == "thermal":
        # Professional Grading: Black -> Deep Purple -> Red -> Orange -> Yellow -> White
        pos = np.array([0.0, 0.15, 0.4, 0.7, 0.9, 1.0])
        colors = np.array([
            [0,0,0,255],      # 0.0: Black
            [40,0,100,255],   # 0.15: Deep Purple
            [185,0,0,255],    # 0.4: Dark Red
            [255,120,0,255],  # 0.7: Orange
            [255,235,0,255],  # 0.9: Yellow
            [255,255,255,255] # 1.0: White
        ], dtype=np.ubyte)
        
    elif name == "heated":
        # Professional Grading: Black -> Rust -> Burnt Orange -> Orange -> Pale Gold -> White
        pos = np.array([0.0, 0.2, 0.45, 0.7, 0.9, 1.0])
        colors = np.array([
            [0, 0, 0, 255],      # 0.0: Black
            [80, 20, 0, 255],    # 0.2: Deep Brown
            [160, 40, 0, 255],   # 0.45: Rust Red
            [255, 140, 0, 255],  # 0.7: Orange
            [255, 235, 100, 255],# 0.9: Pale Gold
            [255, 255, 255, 255] # 1.0: White
        ], dtype=np.ubyte)

    elif name == "bwr":
        pos = np.array([0.0, 0.5, 1.0])
        colors = np.array([
            [0,0,255,255],    # Blue
            [255,255,255,255],# White
            [255,0,0,255]     # Red
        ], dtype=np.ubyte)

    elif name == "bone":
        pos = np.array([0.0, 0.33, 0.66, 1.0])
        colors = np.array([
            [0,0,0,255],         # Black
            [42,49,81,255],      # Deep Blue
            [163,191,198,255],   # Light Blue Gray
            [255,255,255,255]    # White
        ], dtype=np.ubyte)

    elif name == "terrain":
        pos = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
        colors = np.array([
            [0,0,150,255],     # Dark Blue
            [0,0,255,255],     # Blue
            [0,255,0,255],     # Green
            [139,69,19,255],   # Brown
            [255,255,255,255]  # White
        ], dtype=np.ubyte)
        
    else:
        # Fallback to generic
        try:
            pg_cmap = pg.colormap.get(name)
            pos = pg_cmap.pos
            colors = pg_cmap.color
            if colors.dtype.kind == 'f':
                colors = (colors * 255).astype(np.uint8)
        except:
            return get_standard_colormap("thermal", invert, n_levels)

    # 2. Invert if requested
    if invert:
        colors = colors[::-1]
        pos = 1.0 - pos[::-1]
    
    # 3. Handle Quantization (Discrete Levels)
    if n_levels and n_levels > 1:
        temp_cmap = pg.ColorMap(pos, colors)
        new_pos = []
        new_colors = []
        for i in range(n_levels):
            low = i / n_levels
            high = (i + 1) / n_levels
            # Sample at the start of the band for consistent discrete behavior
            # Many pros prefer midpoint, but start is more 'stepped'
            mid = (low + high) / 2
            c = temp_cmap.map(mid, mode='byte')
            # Double stops for hard edges in QLinearGradient
            new_pos.extend([low, high])
            new_colors.extend([c, c])
        pos = np.array(new_pos)
        colors = np.array(new_colors)

    # 4. Construct Objects
    pg_cmap = pg.ColorMap(pos, colors)
    grad = QLinearGradient()
    for p, c in zip(pos, colors):
        grad.setColorAt(float(p), QColor(int(c[0]), int(c[1]), int(c[2]), int(c[3])))
        
    return pg_cmap, grad
