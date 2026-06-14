from PySide6.QtWidgets import QWidget, QDockWidget
from PySide6.QtGui import QColor
from core.app_config import app_config


class ThemeManager:
    """管理应用程序的主题样式，支持从 AppConfig 动态生成 QSS。"""
    
    @classmethod
    def apply_to_main_window(cls, main_window, theme_name=None):
        """Apply main UI QSS. Pulls from AppConfig if theme_name is None."""
        if theme_name is None:
            theme_name = app_config.get_theme_name()
            
        qss = cls.get_main_qss(theme_name)
        main_window.setStyleSheet(qss)
        
        # Propagation for MDI windows and other components
        mdi_bg = app_config.get_theme_color("window_bg")
        if hasattr(main_window, 'mdi_area'):
            main_window.mdi_area.setBackground(QColor(mdi_bg))
        
        # Comprehensive propagation to all children that support update_theme
        for child in main_window.findChildren(QWidget):
            if hasattr(child, 'update_theme'):
                child.update_theme()
            # Special case for DockWidgets: check their inner widget
            if isinstance(child, QDockWidget):
                inner = child.widget()
                if inner and hasattr(inner, 'update_theme'):
                    inner.update_theme()

    @classmethod
    def apply_to_dialog(cls, dialog, theme_name=None):
        """Apply isolated settings QSS. Pulls from AppConfig if theme_name is None."""
        if theme_name is None:
            theme_name = app_config.get_theme_name()
        
        c = lambda t: app_config.get_theme_color(t)
        qss = cls.get_dialog_qss(theme_name)
        
        # Target the main frame for background and border, since the QDialog itself is now transparent
        if hasattr(dialog, 'main_frame'):
            qss += f"""
                QWidget#dialogMainFrame {{ 
                    background-color: {c('dialog_bg')}; 
                    border: 1px solid {c('border_std')};
                    border-radius: 2px;
                }}
                QWidget#dialogContainer {{ background-color: {c('dialog_bg')}; border: none; }}
            """
            
            # Update Shadow Color and Style based on theme
            if hasattr(dialog, '_shadow'):
                if theme_name == "Manga":
                    # Hard offset shadow for comic look
                    dialog._shadow.setBlurRadius(2)
                    dialog._shadow.setXOffset(5)
                    dialog._shadow.setYOffset(5)
                    dialog._shadow.setColor(QColor(0, 0, 0, 255)) # Solid black shadow
                elif theme_name == "Light":
                    dialog._shadow.setBlurRadius(20)
                    dialog._shadow.setXOffset(0)
                    dialog._shadow.setYOffset(2)
                    dialog._shadow.setColor(QColor(0, 0, 0, 80)) # Lighter shadow
                else:
                    dialog._shadow.setBlurRadius(20)
                    dialog._shadow.setXOffset(0)
                    dialog._shadow.setYOffset(2)
                    dialog._shadow.setColor(QColor(0, 0, 0, 180)) # Stronger shadow
        
        dialog.setStyleSheet(qss)
        
        # Propagate to title bar if present
        if hasattr(dialog, 'title_bar'):
            dialog.title_bar.update_theme()
            
        # Recursive propagation for settings framework classes
        if hasattr(dialog, 'update_theme'):
            dialog.update_theme()

    @classmethod
    def apply_curve_table_surface(cls, widget, theme_name=None):
        """Apply shared table-workbench styling to non-dialog widgets."""
        curve_qss = cls.get_curve_table_surface_qss(theme_name)
        existing_qss = widget.styleSheet() or ""
        if existing_qss:
            widget.setStyleSheet(f"{existing_qss}\n{curve_qss}")
        else:
            widget.setStyleSheet(curve_qss)
            
    @classmethod
    def get_main_qss(cls, theme_name=None):
        """Generate QSS for the Main Application UI."""
        c = lambda t: app_config.get_theme_color(t)
        is_manga = theme_name == "Manga"
        b_weight = "2px" if is_manga else "1px"
        b_radius = "0px" if is_manga else "4px"
        
        return f"""
            QMainWindow {{ 
                background-color: {c('window_bg')}; 
                color: {c('text_main')}; 
                border: {b_weight} solid {c('border_dark')};
            }}
            QMainWindow[maximized="true"] {{ border: none; }}
            QMainWindow[maximized="true"] * {{ border-top: none; border-left: none; border-right: none; }}
            QDockWidget {{ color: {c('text_main')}; border: {b_weight} solid {c('border_std')}; font-weight: bold; }}
            QDockWidget::title {{ background: {c('bg_pure')}; padding: 6px; border-bottom: {b_weight} solid {c('border_std')}; font-weight: bold; }}
            
            QMdiSubWindow::title {{ background: {c('bg_pure')}; padding: 4px; font-weight: bold; color: {c('text_main')}; }}
            
            QMainWindow::separator {{ background-color: {c('border_dark')}; width: {b_weight}; height: {b_weight}; }}

            QStatusBar {{
                background-color: {c('bg_pure')};
                color: {c('text_main')};
                border: none;
            }}
            QStatusBar::item {{
                border: none;
            }}
            QSizeGrip {{
                background: transparent;
                width: 12px;
                height: 12px;
            }}
            
            QTreeWidget, QTextEdit {{ background-color: {c('tree_bg')}; color: {c('text_main')}; border: none; }}
            QHeaderView::section {{ 
                background-color: {c('explorer_header_bg')}; 
                color: {c('text_main')}; 
                border: none; 
                border-bottom: {b_weight} solid {c('border_std')}; 
                padding: 3px; 
                font-weight: bold;
            }}
            
            QTreeWidget::item {{ padding: 4px; }}
            QTreeWidget::item:selected {{ background-color: {c('tree_item_selected_bg')}; color: {c('tree_item_selected_text')}; }}
            QTreeWidget::item:hover {{ background-color: {c('tree_item_border')}; }}
            
            QMenuBar {{ background-color: {c('bg_pure')}; color: {c('text_main')}; border-bottom: {b_weight} solid {c('border_std')}; font-size: 11pt; }}
            QMenuBar::item {{ padding: 6px 12px; margin: 2px; border-radius: {b_radius}; }}
            QMenuBar::item:selected {{ background-color: {c('accent_light')}; color: {c('accent')}; }}
            
            QMenu {{ 
                background-color: {c('bg_pure')}; 
                color: {c('text_main')}; 
                border: {b_weight} solid {c('border_std')}; 
                padding: 4px;
            }}
            QMenu::item {{ 
                padding: 6px 24px 6px 24px; 
                border-radius: {b_radius}; 
                margin: 2px 4px; 
            }}
            QMenu::item:selected {{ 
                background-color: {c('accent_light')}; 
                color: {c('accent')}; 
            }}
            QMenu::separator {{ 
                height: {b_weight}; 
                background: {c('border_std')}; 
                margin: 4px 10px; 
            }}
            
            QTabBar {{
                background-color: {c('bg_dim')};
                qproperty-drawBase: 0;
                border: none;
            }}
            QTabBar::tab {{
                background: {c('bg_dim')};
                color: {c('text_dim')};
                padding: 3px 20px;
                border-top-left-radius: {b_radius};
                border-top-right-radius: {b_radius};
                margin-right: 2px;
                border: {b_weight} solid transparent;
            }}
            QTabBar::tab:selected {{
                background: {c('bg_pure')};
                color: {c('text_main')};
                border-bottom: 2px solid {c('accent')};
                font-weight: bold;
            }}
            
            QCheckBox, QRadioButton {{ spacing: 8px; color: {c('text_main')}; }}
            QCheckBox::indicator, QRadioButton::indicator {{ 
                width: 14px; height: 14px; 
                border: {b_weight} solid {c('border_std')}; 
                border-radius: {b_radius};
                background: {c('bg_pure')};
            }}
            QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {c('accent')}; }}
            QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background-color: {c('accent')}; border-color: {c('accent')}; }}

            /* Global Input Styling for Main Window (Search boxes, etc) */
            QLineEdit {{
                border: {b_weight} solid {c('border_std')};
                border-radius: {b_radius};
                padding: 4px 8px;
                background: {c('bg_pure')};
                color: {c('text_main')};
            }}
            QLineEdit:focus {{ border-color: {c('accent')}; }}
        """

    @classmethod
    def get_dialog_qss(cls, theme_name=None):
        """Generate QSS for settings dialogs."""
        c = lambda t: app_config.get_theme_color(t)
        is_manga = theme_name == "Manga"
        b_weight = "2px" if is_manga else "1px"
        b_radius = "0px" if is_manga else "4px"
        
        # Triangle drawing helper (avoids 'transparent' rendering bugs)
        def tri_down(fg, bg, size=5):
            return f"border-left: {size}px solid {bg}; border-right: {size}px solid {bg}; border-top: {size}px solid {fg};"
        
        def tri_up(fg, bg, size=4):
            return f"border-left: {size}px solid {bg}; border-right: {size}px solid {bg}; border-bottom: {size}px solid {fg};"
        
        return f"""
            QDialog {{ background-color: {c('dialog_bg')}; color: {c('text_main')}; }}
            QLabel {{ color: {c('text_main')}; }}
            
            QGroupBox {{
                font-weight: bold;
                border: {b_weight} solid {c('border_dark')};
                border-radius: {b_radius};
                margin-top: 12px;
                padding-top: 15px;
                font-size: 11px;
                color: {c('text_main')};
            }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; color: {c('accent')}; }}
            
            /* --- Premium Input Styling (QLineEdit, SpinBox, ComboBox) --- */
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QFontComboBox {{
                border: {b_weight} solid {c('input_border')};
                border-radius: {b_radius};
                padding: 5px 8px;
                background: {c('input_bg')};
                color: {c('text_main')};
                selection-background-color: {c('accent')};
                selection-color: #FFFFFF;
            }}
            
            QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
                border-color: {c('border_dark')};
            }}
            
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QFontComboBox:focus {{
                border: {b_weight} solid {c('accent')};
                background: {c('bg_pure')};
            }}
            
            /* --- Custom ComboBox Styling --- */
            QComboBox {{
                combobox-popup: 0;
                padding-right: 25px; /* Space for the arrow */
            }}
            
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border: none;
                background: transparent;
            }}
            
            QComboBox::down-arrow {{
                image: none;
                width: 0px; height: 0px;
                {tri_down(c('text_dim'), c('input_bg'))}
                margin-right: 8px;
            }}
            
            QComboBox::down-arrow:on {{
                {tri_up(c('accent'), c('input_bg'))}
            }}
            
            QComboBox:focus QComboBox::down-arrow {{
                {tri_down(c('text_dim'), c('bg_pure'), 5)}
            }}
            
            QComboBox QAbstractItemView {{
                background-color: {c('bg_pure')};
                color: {c('text_main')};
                selection-background-color: {c('accent_light')};
                selection-color: {c('accent')};
                border: {b_weight} solid {c('border_std')};
                outline: 0px;
                padding: 4px;
                border-radius: {b_radius};
            }}
            
            QComboBox QAbstractItemView::item {{
                padding: 6px 10px;
                border-radius: 2px;
                margin: 2px 0;
            }}
            
            /* --- Custom SpinBox Styling (Integrated buttons) --- */
            QSpinBox::up-button, QDoubleSpinBox::up-button,
            QSpinBox::down-button, QDoubleSpinBox::down-button {{
                width: 18px;
                border: none;
                background: transparent;
            }}
            
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
                background-color: {c('bg_dim')};
            }}
            
            QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
                image: none;
                width: 0px; height: 0px;
                {tri_up(c('text_dim'), c('input_bg'), 4)}
            }}
            
            QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
                image: none;
                width: 0px; height: 0px;
                {tri_down(c('text_dim'), c('input_bg'), 4)}
            }}

            QCheckBox, QRadioButton {{ spacing: 8px; color: {c('text_main')}; }}
            QCheckBox::indicator, QRadioButton::indicator {{ 
                width: 16px; height: 16px; 
                border: {b_weight} solid {c('border_dark')}; 
                border-radius: {b_radius};
                background: {c('input_bg')};
            }}
            QCheckBox::indicator:hover {{ border-color: {c('accent')}; }}
            QCheckBox::indicator:checked {{ 
                background-color: {c('accent')}; 
                border-color: {c('accent')};
            }}
            
            QPushButton {{
                background-color: {c('button_bg')};
                border: {b_weight} solid {c('input_border')};
                border-radius: {b_radius};
                padding: 6px 18px;
                color: {c('text_main')};
                min-width: 80px;
                font-weight: 500;
            }}
            QPushButton:hover {{ 
                background-color: {c('button_hover')}; 
                border-color: {c('border_dark')}; 
            }}
            QPushButton:pressed {{ background-color: {c('border_dark')}; }}
            QPushButton:default {{ 
                background-color: {c('primary')}; 
                border: {b_weight} solid {c('primary')};
                color: #FFFFFF;
                font-weight: bold;
            }}
            QPushButton:default:hover {{ background-color: {c('primary_hover')}; border-color: {c('primary_hover')}; }}
            QPushButton:default:pressed {{ background-color: {c('primary_pressed')}; border-color: {c('primary_pressed')}; }}
            
            QTabWidget {{ background-color: {c('dialog_bg')}; }}
            QTabWidget::pane {{ border: {b_weight} solid {c('border_std')}; border-radius: {b_radius}; top: -1px; background: {c('bg_pure')}; }}
            QTabBar::tab {{
                background: {c('button_bg')};
                color: {c('text_dim')};
                padding: 6px 15px;
                border: {b_weight} solid {c('border_std')};
                border-bottom: none;
                border-top-left-radius: {b_radius};
                border-top-right-radius: {b_radius};
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{ background: {c('bg_pure')}; color: {c('accent')}; font-weight: bold; border-bottom: 2px solid {c('bg_pure')}; }}
            
            QListWidget {{
                border: {b_weight} solid {c('input_border')};
                border-radius: {b_radius};
                background-color: {c('bg_pure')};
                outline: none;
            }}
            QListWidget::item {{ padding: 8px; color: {c('text_main')}; border-bottom: {b_weight} solid {c('tree_item_border')}; }}
            QListWidget::item:selected {{ background-color: {c('accent_light')}; color: {c('accent')}; }}
            
            QProgressBar {{ border: {b_weight} solid {c('input_border')}; border-radius: {b_radius}; text-align: center; background-color: {c('button_bg')}; }}
            QProgressBar::chunk {{ background-color: {c('success')}; width: 10px; margin: 0.5px; }}
            
            QScrollBar:vertical {{
                background: {c('input_bg')};
                width: 12px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {c('scrollbar_handle')};
                min-height: 20px;
                border-radius: {b_radius};
                margin: 2px;
                border: {b_weight} solid {c('border_dark')};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            
            QScrollBar:horizontal {{
                background: {c('input_bg')};
                height: 12px;
                margin: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background: {c('scrollbar_handle')};
                min-width: 20px;
                border-radius: {b_radius};
                margin: 2px;
                border: {b_weight} solid {c('border_dark')};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
            
            QTableWidget, QTableView, QHeaderView {{
                background-color: {c('bg_pure')};
                color: {c('text_main')};
                gridline-color: {c('border_std')};
            }}
            QHeaderView::section {{
                background-color: {c('explorer_header_bg')};
                border: {b_weight} solid {c('border_std')};
            }}
        """

    @classmethod
    def get_curve_table_surface_qss(cls, theme_name=None):
        """Shared QSS for curve-table workbenches used in dialogs and MDI pages."""
        if theme_name is None:
            theme_name = app_config.get_theme_name()

        c = lambda t: app_config.get_theme_color(t)
        is_manga = theme_name == "Manga"
        b_weight = "2px" if is_manga else "1px"
        b_radius = "0px" if is_manga else "4px"
        table_frame_weight = "1px"

        return f"""
            QWidget {{
                background-color: {c('window_bg')};
                color: {c('text_main')};
            }}
            QWidget#curveTableToolbar {{
                background-color: {c('bg_pure')};
                border: {b_weight} solid {c('border_dark')};
                border-radius: {b_radius};
                padding: 10px;
            }}
            QWidget#curveTableRoot {{
                background-color: {c('window_bg')};
            }}
            QLabel#curveTableTitle {{
                color: {c('accent')};
                font-size: 15px;
                font-weight: bold;
                padding: 0 2px;
                background: transparent;
            }}
            QLabel#curveTableStatus {{
                color: {c('text_dim')};
                background-color: {c('bg_header')};
                border-left: 3px solid {c('accent')};
                border-top: {b_weight} solid {c('border_std')};
                border-bottom: {b_weight} solid {c('border_std')};
                padding: 6px 10px;
            }}
            QLabel {{
                color: {c('text_main')};
            }}
            QLineEdit {{
                border: {b_weight} solid {c('input_border')};
                border-radius: {b_radius};
                padding: 5px 8px;
                background: {c('input_bg')};
                color: {c('text_main')};
            }}
            QLineEdit:focus {{
                border-color: {c('accent')};
                background: {c('bg_pure')};
            }}
            QPushButton {{
                background-color: {c('button_bg')};
                border: {b_weight} solid {c('input_border')};
                border-radius: {b_radius};
                padding: 6px 18px;
                color: {c('text_main')};
                min-width: 80px;
                font-weight: 500;
            }}
            QWidget#curveTableToolbar QPushButton {{
                min-width: 96px;
            }}
            QPushButton:hover {{
                background-color: {c('button_hover')};
                border-color: {c('border_dark')};
            }}
            QPushButton:pressed {{
                background-color: {c('border_dark')};
            }}
            QPushButton:default {{
                background-color: {c('primary')};
                border: {b_weight} solid {c('primary')};
                color: #FFFFFF;
                font-weight: bold;
            }}
            QPushButton:default:hover {{
                background-color: {c('primary_hover')};
                border-color: {c('primary_hover')};
            }}
            QPushButton:default:pressed {{
                background-color: {c('primary_pressed')};
                border-color: {c('primary_pressed')};
            }}
            QAbstractScrollArea {{
                background-color: {c('bg_pure')};
                border: none;
            }}
            QAbstractScrollArea > QWidget {{
                background-color: {c('bg_pure')};
            }}
            QTableWidget, QTableView {{
                background-color: {c('bg_pure')};
                color: {c('text_main')};
                gridline-color: {c('border_std')};
                selection-background-color: {c('accent_light')};
                selection-color: {c('text_main')};
                alternate-background-color: {c('bg_pure')};
                border: {table_frame_weight} solid {c('border_std')};
            }}
            QTableView {{
                border-radius: {b_radius};
                outline: none;
            }}
            QTableView::item, QTableWidget::item {{
                padding: 2px 6px;
                border: none;
            }}
            QTableView::item:selected, QTableWidget::item:selected {{
                background-color: {c('accent_light')};
                color: {c('text_main')};
            }}
            QHeaderView::section:horizontal {{
                background-color: {c('explorer_header_bg')};
                color: {c('text_main')};
                border: none;
                border-right: {table_frame_weight} solid {c('border_std')};
                border-bottom: {table_frame_weight} solid {c('border_std')};
                padding: 4px 6px;
                font-weight: bold;
            }}
            QHeaderView::section:vertical {{
                background-color: {c('bg_pure')};
                color: {c('text_main')};
                border: none;
                border-bottom: {b_weight} solid {c('border_std')};
                padding: 2px 4px;
                font-weight: normal;
            }}
            QTableCornerButton::section {{
                background-color: {c('bg_pure')};
                border: none;
                border-bottom: {b_weight} solid {c('border_std')};
            }}
            QScrollBar:vertical {{
                background: {c('input_bg')};
                width: 12px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {c('scrollbar_handle')};
                min-height: 20px;
                border-radius: {b_radius};
                margin: 2px;
                border: {b_weight} solid {c('border_dark')};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            QScrollBar:horizontal {{
                background: {c('input_bg')};
                height: 12px;
                margin: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background: {c('scrollbar_handle')};
                min-width: 20px;
                border-radius: {b_radius};
                margin: 2px;
                border: {b_weight} solid {c('border_dark')};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
        """

    @classmethod
    def get_web_theme_vars(cls, theme_name=None):
        """Get a dictionary of theme tokens for web views."""
        if theme_name is None:
            theme_name = app_config.get_theme_name()
        
        c = lambda t: app_config.get_theme_color(t)
        
        # Standardized mapping between AppConfig and Web CSS variables
        return {
            "--bg-primary": c("bg_pure"),
            "--bg-secondary": c("bg_app"),
            "--bg-tertiary": c("bg_header"),
            "--bg-dim": c("bg_dim"),
            "--text-primary": c("text_main"),
            "--text-secondary": c("text_dim"),
            "--border-color": c("border_std"),
            "--border-light": c("border_dark"),
            "--accent-color": c("accent"),
            "--primary-color": c("primary"),
            "--info-bg": c("accent_light"),
            "--success-color": c("success"),
            "--danger-color": c("danger"),
            "--warning-color": c("warning"),
            
            # Artistic Style Tokens (Manga focus)
            "--wc-user": c("wc_user"),
            "--wc-pill": c("wc_pill"),
            "--wc-gold": c("wc_gold"),
            "--border-ink": c("border_ink"),
            "--shadow-hard": c("shadow_hard"),
        }

    @classmethod
    def get_web_theme_css(cls, theme_name=None):
        """Generate a :root CSS variable block for web templates."""
        vars_dict = cls.get_web_theme_vars(theme_name)
        css_lines = [":root {"]
        for key, val in vars_dict.items():
            css_lines.append(f"    {key}: {val};")
        css_lines.append("}")
        return "\n".join(css_lines)
