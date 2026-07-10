"""
MenuManager - 负责 MainWindow 菜单栏的构建和信号连接。
从 MainWindow.create_menu 中提取，遵循单一职责原则。
"""
from PySide6.QtGui import QAction, QActionGroup


class MenuManager:
    """构建和管理 MainWindow 的全部菜单。"""
    
    def __init__(self, main_window, menu_bar=None):
        self.mw = main_window
        self.menu_bar = menu_bar
        self._build_menus()
    
    def _build_menus(self):
        """构建所有菜单栏和动作。"""
        mw = self.mw
        menu = self.menu_bar if self.menu_bar else mw.menuBar()

        # --- Actions ---
        mw.new_plot_action = QAction("Plot", mw)
        mw.new_plot_action.triggered.connect(mw.new_plot_window)
        mw.export_action = QAction("Export Plot (JPG/PDF)...", mw)
        mw.export_action.triggered.connect(mw.handle_export_plot)
        mw.export_action.setShortcut("Ctrl+E")
        
        mw.import_action = QAction("Import DLIS...", mw)
        mw.import_action.triggered.connect(mw.handle_import_dlis)
        mw.export_dlis_action = QAction("Export DLIS...", mw)
        mw.export_dlis_action.triggered.connect(mw.handle_export_dlis)

        # --- File Menu ---
        file_menu = menu.addMenu("File")
        file_menu.addAction(mw.import_action)
        file_menu.addAction(mw.export_dlis_action)
        file_menu.addSeparator()
        file_menu.addAction(mw.export_action)
        file_menu.addSeparator()
        
        exit_action = QAction("Exit", mw)
        exit_action.triggered.connect(mw.close)
        file_menu.addAction(exit_action)
        
        file_menu.addSeparator()
        
        mw.about_action = QAction("About", mw)
        mw.about_action.triggered.connect(mw.handle_about)
        file_menu.addAction(mw.about_action)

        # --- View Menu ---
        view_menu = menu.addMenu("View")
        
        mw.toggle_explorer_action = QAction("Explorer", mw)
        mw.toggle_explorer_action.setCheckable(True)
        mw.toggle_explorer_action.setChecked(True)
        mw.toggle_explorer_action.triggered.connect(mw.toggle_explorer)
        view_menu.addAction(mw.toggle_explorer_action)
        
        # --- Plugins Menu ---
        mw.plugin_menu = menu.addMenu("Plugins")
        
        ai_action = QAction("AI Assistant", mw)
        ai_action.setShortcut("Ctrl+Shift+A")
        ai_action.triggered.connect(mw.show_ai_assistant)
        mw.plugin_menu.addAction(ai_action)
        
        if mw._show_scripts:
            script_action = QAction("New Script", mw)
            script_action.setShortcut("Ctrl+N")
            script_action.triggered.connect(mw.new_script_window)
            mw.plugin_menu.addAction(script_action)
        
        view_menu.addSeparator()
        
        # --- Performance Optimizations ---
        mw.skip_finite_action = QAction("Skip Finite Check", mw)
        mw.skip_finite_action.setCheckable(True)
        mw.skip_finite_action.setChecked(True)
        mw.skip_finite_action.triggered.connect(mw.toggle_skip_finite_check)
        view_menu.addAction(mw.skip_finite_action)
        
        mw.antialias_action = QAction("Antialias", mw)
        mw.antialias_action.setCheckable(True)
        mw.antialias_action.setChecked(False)
        mw.antialias_action.triggered.connect(mw.toggle_antialias)
        view_menu.addAction(mw.antialias_action)
        
        mw.enable_effects_action = QAction("Header Glass Effect", mw)
        mw.enable_effects_action.setCheckable(True)
        from core.app_config import app_config
        mw.enable_effects_action.setChecked(app_config.get_header_effects_enabled())
        mw.enable_effects_action.triggered.connect(mw.toggle_effects)
        view_menu.addAction(mw.enable_effects_action)
        
        view_menu.addSeparator()
        
        # --- Theme Submenu ---
        from core.app_config import app_config
        current_theme = app_config.get_theme_name()
        
        theme_menu = view_menu.addMenu("Theme")
        theme_group = QActionGroup(mw)
        theme_group.setExclusive(True)
        
        light_action = QAction("Light", mw)
        light_action.setCheckable(True)
        light_action.setChecked(current_theme == "Light")
        light_action.triggered.connect(lambda: mw.apply_theme("Light"))
        theme_menu.addAction(light_action)
        theme_group.addAction(light_action)
        
        dark_action = QAction("Dark", mw)
        dark_action.setCheckable(True)
        dark_action.setChecked(current_theme == "Dark")
        dark_action.triggered.connect(lambda: mw.apply_theme("Dark"))
        theme_menu.addAction(dark_action)
        theme_group.addAction(dark_action)

        sakura_action = QAction("Midnight Sakura", mw)
        sakura_action.setCheckable(True)
        sakura_action.setChecked(current_theme == "Sakura")
        sakura_action.triggered.connect(lambda: mw.apply_theme("Sakura"))
        theme_menu.addAction(sakura_action)
        theme_group.addAction(sakura_action)

        manga_action = QAction("Manga", mw)
        manga_action.setCheckable(True)
        manga_action.setChecked(current_theme == "Manga")
        manga_action.triggered.connect(lambda: mw.apply_theme("Manga"))
        theme_menu.addAction(manga_action)
        theme_group.addAction(manga_action)
        
        view_menu.addSeparator()
        
        # --- Horizontal Scale Submenu ---
        h_scale_menu = view_menu.addMenu("Horizontal Scale")
        for p in [35, 50, 70, 100, 110]:
            act = QAction(f"{p}%", mw)
            act.triggered.connect(lambda checked, val=p / 100.0: mw.handle_horizontal_scale(val))
            h_scale_menu.addAction(act)
        
        # --- Templates Menu ---
        mw.save_template_action = QAction("Save Plot as Template...", mw)
        mw.save_template_action.triggered.connect(mw.handle_save_template)
        mw.apply_template_action = QAction("Open Template...", mw)
        mw.apply_template_action.triggered.connect(mw.handle_apply_template)
        
        template_menu = menu.addMenu("Templates")
        template_menu.addAction(mw.save_template_action)
        template_menu.addAction(mw.apply_template_action)

        # Top-Level Actions
        menu.addAction(mw.new_plot_action)

        mw.fracture_action = QAction("Fracture", mw)
        mw.fracture_action.triggered.connect(mw.open_fracture_picking_plot)
        menu.addAction(mw.fracture_action)
