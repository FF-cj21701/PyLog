"""
应用级别配置管理器
用于存储全局应用设置
"""
from PySide6.QtCore import QSettings

class AppConfig:
    """应用配置管理器（单例模式）"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._theme_name = None 
        self.settings = QSettings("PyLog", "Application")
    
    # ========== UI Theme Tokens (Light Focused) ==========
    
    LIGHT_THEME = {
        # --- Base Palette (User only needs to modify these for major changes) ---
        "bg_pure": "#FFFFFF",      # Pure background (Trees, Inputs, Menus)
        "bg_app": "#F5F5F5",       # App-wide window background
        "bg_header": "#F8F9FA",    # Header/Explorer section background
        "bg_dim": "#F0F0F0",       # Secondary backgrounds (Buttons, Tabs)
        
        "text_main": "#333333",    # Primary text
        "text_dim": "#777777",     # Secondary/Hint text
        "border_std": "#E0E0E0",   # Default borders
        "border_dark": "#D0D0D0",  # Stronger borders
        
        "color_accent": "#0078D7",        # Primary brand/action color
        "color_accent_soft": "#EBF3FF",   # Soft selection/highlight color
        "color_success": "#107C10",
        "color_danger": "#E81123",
        "color_warning": "#FF8C00",
        
        # --- Semantic Tokens (Reference the palette above) ---
        "window_bg": "{bg_app}",
        "tree_bg": "{bg_pure}",
        "explorer_header_bg": "{bg_header}",
        "tree_item_border": "{bg_app}",
        "tree_item_selected_bg": "#E8F2FB", # Specific for trees
        "tree_item_selected_text": "#000000",
        
        "dialog_bg": "{bg_pure}",
        "input_bg": "#FAFAFA",
        "input_border": "#CCCCCC",
        "button_bg": "{bg_dim}",
        "button_hover": "{border_std}",
        "special_button_bg": "#FFE8EF",
        "special_button_hover": "#FFD9E3",
        "special_button_text": "#5C1F32",
        
        "accent": "{color_accent}",
        "accent_light": "{color_accent_soft}",
        "accent_hover": "rgba(0, 120, 215, 30)",  # Subtle blue hover
        "item_selected": "rgba(0, 120, 215, 50)",
        
        "primary": "{color_accent}",
        "primary_hover": "#006CC2",
        "primary_pressed": "#005AAB",
        "success": "{color_success}",
        "danger": "{color_danger}",
        "warning": "{color_warning}",
        
        # --- Artistic Tokens ---
        "wc_user": "rgba(59, 130, 246, 0.15)",
        "wc_pill": "rgba(59, 130, 246, 0.1)",
        "wc_gold": "rgba(245, 158, 11, 0.1)",
        "border_ink": "1px solid #E2E8F0",
        "shadow_hard": "0 1px 2px 0 rgba(0, 0, 0, 0.05)",
        
        "plot_bg": "{bg_pure}",
        "track_divider": "#000000",
        "grid_major": "#D8D8D8",
        "grid_minor": "#EFEFEF",
        "scrollbar_handle": "rgba(160, 160, 160, 100)",
        "scrollbar_handle_hover": "rgba(120, 120, 120, 160)",
        "header_glass": "rgba(255, 255, 255, 150)",
    }

    TRACK_DEFAULTS = {
        "width": 204,
        "header_height": 100,
        "default_v_scale": 1.0, # 1:200 typically
    }

    DARK_THEME = {
        # --- Base Palette (Dark Mode) ---
        "bg_pure": "#1E1E1E",      # Deep charcoal
        "bg_app": "#121212",       # Pure near-black
        "bg_header": "#252526",    # Section headers
        "bg_dim": "#2D2D30",       # Secondary (Buttons, Tabs)
        
        "text_main": "#E1E1E1",    # Grey-white text
        "text_dim": "#A0A0A0",     # Dimmer text
        "border_std": "#3F3F46",   # Standard borders
        "border_dark": "#52525B",  # Darker borders
        
        "color_accent": "#26A69A",        # Jade/Teal primary accent
        "color_accent_soft": "#2D4A48",   # Dark greenish highlight
        "color_success": "#2E7D32",
        "color_danger": "#D32F2F",
        "color_warning": "#FBC02D",
        
        # --- Semantic Tokens (Dark Mapping) ---
        "window_bg": "{bg_app}",
        "tree_bg": "{bg_pure}",
        "explorer_header_bg": "{bg_header}",
        "tree_item_border": "{bg_app}",
        "tree_item_selected_bg": "#2A2D2E",
        "tree_item_selected_text": "#FFFFFF",
        
        "dialog_bg": "{bg_pure}",
        "input_bg": "#000000",
        "input_border": "#454545",
        "button_bg": "{bg_dim}",
        "button_hover": "#3E3E42",
        "special_button_bg": "#3A2A30",
        "special_button_hover": "#49323A",
        "special_button_text": "#F0D8DF",
        
        "accent": "{color_accent}",
        "accent_light": "{color_accent_soft}",
        "accent_hover": "rgba(38, 166, 154, 40)",
        "item_selected": "rgba(38, 166, 154, 60)",
        
        "primary": "{color_accent}",
        "primary_hover": "#4DB6AC",
        "primary_pressed": "#00897B",
        "success": "{color_success}",
        "danger": "{color_danger}",
        "warning": "{color_warning}",
        
        # --- Artistic Tokens ---
        "wc_user": "rgba(38, 166, 154, 0.15)",
        "wc_pill": "rgba(38, 166, 154, 0.1)",
        "wc_gold": "rgba(251, 192, 45, 0.1)",
        "border_ink": "1px solid #3F3F46",
        "shadow_hard": "0 2px 4px rgba(0, 0, 0, 0.2)",
        
        "plot_bg": "#1E1E1E", # Dark grey for plot area
        "track_divider": "#404040",
        "grid_major": "#333333",
        "grid_minor": "#262626",
        "scrollbar_handle": "rgba(255, 255, 255, 60)",
        "scrollbar_handle_hover": "rgba(255, 255, 255, 100)",
        "header_glass": "rgba(30, 30, 30, 200)",
    }

    SAKURA_THEME = {
        # --- Base Palette (Midnight Sakura) ---
        "bg_pure": "#231224",      # Deep Eggplant
        "bg_app": "#1A0B1A",       # Midnight Purple
        "bg_header": "#2D162E",    # Dark Magenta
        "bg_dim": "#351B38",       # Muted Purple
        
        "text_main": "#F8EBF0",    # Sakura White
        "text_dim": "#B8A0B8",     # Lavender Grey
        "border_std": "#4A234D",   # Plum Border
        "border_dark": "#602E63",  # Strong Plum
        
        "color_accent": "#FF69B4",        # Hot Pink
        "color_accent_soft": "#4A1A2C",   # Dark Rose highlight
        "color_success": "#4CAF50",
        "color_danger": "#FF5252",
        "color_warning": "#FFD740",
        
        # --- Semantic Tokens ---
        "window_bg": "{bg_app}",
        "tree_bg": "{bg_pure}",
        "explorer_header_bg": "{bg_header}",
        "tree_item_border": "{bg_app}",
        "tree_item_selected_bg": "#3E1C40",
        "tree_item_selected_text": "#FFFFFF",
        
        "dialog_bg": "{bg_pure}",
        "input_bg": "#120512",
        "input_border": "#552A58",
        "button_bg": "{bg_dim}",
        "button_hover": "#452449",
        "special_button_bg": "#4A1A2C",
        "special_button_hover": "#5A2238",
        "special_button_text": "#FFEAF3",
        
        "accent": "{color_accent}",
        "accent_light": "{color_accent_soft}",
        "accent_hover": "rgba(255, 105, 180, 40)",
        "item_selected": "rgba(255, 105, 180, 60)",
        
        "primary": "{color_accent}",
        "primary_hover": "#FF85C1",
        "primary_pressed": "#F06292",
        "success": "{color_success}",
        "danger": "{color_danger}",
        "warning": "{color_warning}",
        
        # --- Artistic Tokens ---
        "wc_user": "rgba(255, 105, 180, 0.15)",
        "wc_pill": "rgba(255, 105, 180, 0.1)",
        "wc_gold": "rgba(255, 215, 64, 0.1)",
        "border_ink": "1px solid #4A234D",
        "shadow_hard": "0 2px 4px rgba(0, 0, 0, 0.3)",
        
        "plot_bg": "#231224",
        "track_divider": "#502854",
        "grid_major": "#3D1F40",
        "grid_minor": "#2C162E",
        "scrollbar_handle": "rgba(255, 105, 180, 80)",
        "scrollbar_handle_hover": "rgba(255, 105, 180, 130)",
        "header_glass": "rgba(35, 18, 36, 210)",
    }

    MANGA_THEME = {
        # --- Base Palette (Manga / Paper) ---
        "bg_pure": "#FDFBF5",      # Warm paper white
        "bg_app": "#F9F7F0",       # Paper margin
        "bg_header": "#FDFBF5",    # Slightly darker paper
        "bg_dim": "#E5E1D4",       # Muted Paper
        
        "text_main": "#121212",    # Ink black
        "text_dim": "#555555",     # Charcoal Grey
        "border_std": "#000000",   # Solid ink lines
        "border_dark": "#000000",  # Strong ink lines
        
        "color_accent": "#000000",        # Pure black accent
        "color_accent_soft": "#F5F2E8",   # Very light paper highlight
        "color_success": "#1E5128",       # Dark Forest Ink
        "color_danger": "#812B33",        # Dark Crimson Ink
        "color_warning": "#A0522D",       # Sienna/Brown Ink
        
        # --- Semantic Tokens ---
        "window_bg": "{bg_app}",
        "tree_bg": "{bg_pure}",
        "explorer_header_bg": "{bg_header}",
        "tree_item_border": "{bg_app}",
        "tree_item_selected_bg": "#F5F2E8",
        "tree_item_selected_text": "#000000",
        
        "dialog_bg": "{bg_pure}",
        "input_bg": "#FDFBF5",
        "input_border": "#000000",
        "button_bg": "{bg_dim}",
        "button_hover": "#CFCAB6",
        "special_button_bg": "#F7E3E8",
        "special_button_hover": "#EED1DA",
        "special_button_text": "#121212",
        
        "accent": "{color_accent}",
        "accent_light": "{color_accent_soft}",
        "accent_hover": "rgba(0, 0, 0, 20)",
        "item_selected": "rgba(0, 0, 0, 40)",
        
        "primary": "{color_accent}",
        "primary_hover": "#222222",
        "primary_pressed": "#111111",
        "success": "{color_success}",
        "danger": "{color_danger}",
        "warning": "{color_warning}",
        
        # --- Artistic Tokens (Manga Watercolor Architecture) ---
        "wc_user": "rgba(224, 231, 255, 0.7)",      # Slate Blue Wash
        "wc_pill": "rgba(255, 235, 245, 0.7)",      # Pale Pink Wash
        "wc_gold": "rgba(255, 248, 220, 0.8)",      # Pale Gold Wash
        "border_ink": "1.5px solid #121212",        # Hard Ink Stroke
        "shadow_hard": "2.5px 2.5px 0px rgba(0,0,0,0.1)", # Solid Offset Shadow
        
        "plot_bg": "#FCFAF2",
        "track_divider": "#000000",
        "grid_major": "#D8D8D8",
        "grid_minor": "#EFEFEF",
        "scrollbar_handle": "rgba(0, 0, 0, 100)",
        "scrollbar_handle_hover": "rgba(0, 0, 0, 160)",
        "header_glass": "rgba(253, 251, 245, 180)",
    }

    def theme_context(self, name):
        """
        Context manager to temporarily override the active theme.
        Used primarily for rendering exports in Light mode while the UI stays in another theme.
        """
        class ThemeContext:
            def __init__(self, config, theme_name):
                self.config = config
                self.theme_name = theme_name
                self.old_theme = config._theme_name # Use internal variable to avoid settings load
            def __enter__(self):
                self.config._theme_name = self.theme_name
                return self.config
            def __exit__(self, exc_type, exc_val, exc_tb):
                self.config._theme_name = self.old_theme
        return ThemeContext(self, name)

    def get_theme_name(self):
        """Get current theme name ('Light' or 'Dark')."""
        if self._theme_name is None:
            self._theme_name = self.settings.value("theme_name", "Light")
        return self._theme_name

    def set_theme_name(self, name):
        """Set current theme and save."""
        self._theme_name = name
        self.settings.setValue("theme_name", name)

    def get_theme_color(self, token, default="#000000"):
        """Get color for the active theme, resolving palette references."""
        theme_name = self.get_theme_name()
        if theme_name == "Dark":
            theme = self.DARK_THEME
        elif theme_name == "Sakura":
            theme = self.SAKURA_THEME
        elif theme_name == "Manga":
            theme = self.MANGA_THEME
        else:
            theme = self.LIGHT_THEME
        val = theme.get(token, default)
        
        # Resolve simple {palette_ref} (one level deep)
        if isinstance(val, str) and val.startswith("{") and val.endswith("}"):
            ref = val[1:-1]
            return theme.get(ref, val)
        return val

    # Alias for backward compatibility if needed, but discouraged
    def get_color(self, name, default="#000000"):
        return self.get_theme_color(name, default)

    def get_theme_qcolor(self, token, default="#000000"):
        """Get a QColor object for a token, handling rgba() parsing."""
        from PySide6.QtGui import QColor
        val = self.get_theme_color(token, default)
        if isinstance(val, str) and val.startswith("rgba("):
            try:
                # Simple parser for "rgba(r, g, b, a)"
                s = val.replace("rgba(", "").replace(")", "").replace(" ", "")
                parts = s.split(",")
                r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                a = int(parts[3])
                return QColor(r, g, b, a)
            except:
                pass
        return QColor(val)

    def resolve_null_color(self, val):
        """Resolve 'Auto' or specific 'White'/'Black' to a solid color name or 'Theme'."""
        if val == "Auto" or val is None or val == "":
            return "Theme"
        return val

    # ========== AI助手设置 ==========
    
    def get_ai_auto_load(self):
        """获取AI助手是否默认自动加载"""
        return self.settings.value("ai_auto_load", True, bool)
    
    def set_ai_auto_load(self, enabled):
        """设置AI助手是否默认自动加载"""
        self.settings.setValue("ai_auto_load", enabled)

    # ========== 视觉效果设置 ==========
    
    def get_header_effects_enabled(self):
        """获取是否启用图形表头特效（毛玻璃效果）"""
        return self.settings.value("show_header_effects", True, type=bool)

    def set_header_effects_enabled(self, enabled):
        """设置是否启用图形表头特效（毛玻璃效果）"""
        self.settings.setValue("show_header_effects", enabled)

# 全局配置实例
app_config = AppConfig()
