import sys
import os
import traceback
import asyncio
import qasync
import sniffio
# [CRITICAL] Global sniffio patch to prevent AsyncLibraryNotFoundError during async teardown.
# This forces all libraries to recognize the asyncio event loop.
sniffio.current_async_library = lambda: "asyncio"

from PySide6.QtCore import Qt, QCoreApplication, QTimer

# [CRITICAL FIX] Enable OpenGL Context Sharing and Desktop OpenGL for WebEngine stability.
# This prevents crashes/flickering and ensures HW acceleration works correctly.
QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
QCoreApplication.setAttribute(Qt.AA_UseDesktopOpenGL)

from PySide6.QtWidgets import (QApplication, QMainWindow, QDockWidget, QTreeWidget, QTreeWidgetItem, 
                               QMdiArea, QMdiSubWindow, QFileDialog, QMenuBar, QMenu, QMessageBox, 
                               QInputDialog, QStyle, QHeaderView, QWidget, QVBoxLayout, QHBoxLayout,
                               QTextEdit, QAbstractItemView, QFrame, QDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QDialogButtonBox,
                               QProgressBar, QSlider, QWidgetAction)
from PySide6.QtCore import QMimeData, QTimer, QEvent, QThread, Signal, QObject
from PySide6.QtGui import QAction, QIcon, QColor, QDrag, QKeySequence
from scripts.data.db_manager import DBManager
from scripts.data.dlis_importer import import_dlis, get_dlis_info
from scripts.data.template_manager import TemplateManager
from scripts.rendering.plot_widget import LogWidget
from scripts.services.plot_spec_service import build_plot_spec_from_manual_items, open_plot_from_spec
from scripts.ui.ui_explorer import UnifiedExplorer
from scripts.data.export_manager import LogExporter
from scripts.utils.workers import DataFetchWorker
from scripts.ui.floating_scrollbar import FloatingScrollbarManager
from scripts.ui.plot_dialogs import UnitEditDialog
from scripts.data.import_workers import ImportWorker, ExportWorker
from scripts.ui.dialogs.import_dialogs import DLISImportDialog
from scripts.ui.dialogs.export_dialogs import DLISExportDialog, DLISExportResultDialog
from scripts.data.dlis_exporter import export_well_to_dlis
from scripts.ui.widgets.data_viewer_widget import DataViewerWidget
from scripts.ui.widgets.html_preview_widget import HtmlPreviewWidget, is_html_previewable
from scripts.ui.widgets.workspace_launchpad_widget import WorkspaceLaunchpadWidget
from scripts.utils.well_metadata import get_well_export_snapshot
from core.app_config import app_config
from scripts.utils.logger import logger
from scripts.ui.custom_title_bar import ModernTitleBar
from scripts.ui.frameless_helper import FramelessHelper
from scripts.ui.base_dialog import ThemeDialog
import pylog_api

def global_exception_handler(exctype, value, tb):
    """
    Global exception handler to capture all unhandled exceptions and show a dialog.
    """
    # Ignore keyboard interrupt (Ctrl+C) as it's usually intentional
    if issubclass(exctype, KeyboardInterrupt):
        sys.__excepthook__(exctype, value, tb)
        return

    error_msg = "".join(traceback.format_exception(exctype, value, tb))
    logger.critical(f"Unhandled Exception: {error_msg}")
    
    # Show a message box if QApplication is running
    if QApplication.instance():
        display_msg = str(value) if str(value) else "An internal error occurred."
        msg_box = QMessageBox(None)
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setWindowTitle("Application Error")
        msg_box.setText(f"An unexpected error occurred: {display_msg}")
        msg_box.setInformativeText("Technical details have been saved to logs/pylog.log.\nWould you like to open the log folder?")
        msg_box.setDetailedText(error_msg)
        
        open_log_btn = msg_box.addButton("Open Log Folder", QMessageBox.ActionRole)
        msg_box.addButton(QMessageBox.Ok)
        
        msg_box.exec()
        
        if msg_box.clickedButton() == open_log_btn:
            try:
                log_dir = os.path.abspath("logs")
                import subprocess
                if sys.platform == 'win32':
                    os.startfile(log_dir)
                elif sys.platform == 'darwin':
                    subprocess.Popen(['open', log_dir])
                else:
                    subprocess.Popen(['xdg-open', log_dir])
            except:
                pass
    
    # Still call the original excepthook
    sys.__excepthook__(exctype, value, tb)

# Register the exception handler
sys.excepthook = global_exception_handler

# --- Main UI Components ---
class MainWindow(QMainWindow):
    plot_selection_changed = Signal(list)
    
    def __init__(self, show_ai_chat=None, show_scripts=True):
        super().__init__()
        # 如果未指定，从配置读取默认值
        if show_ai_chat is None:
            show_ai_chat = app_config.get_ai_auto_load()
        self._show_ai_chat = show_ai_chat
        self._show_scripts = show_scripts
        self.setWindowTitle("ALIVE")
        self.resize(1200, 800)
        
        self.db = None
        
        # 插件管理器
        self.plugin_manager = None
        self._ai_plugin = None
        self._script_plugin = None
        
        # --- Frameless Setup ---
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        
        # MDI Area
        self.mdi_area = QMdiArea()
        self.mdi_area.setViewMode(QMdiArea.TabbedView)
        self.mdi_area.setTabsClosable(True)
        self.mdi_area.setTabsMovable(True)
        self.setCentralWidget(self.mdi_area)
        self.mdi_area.subWindowActivated.connect(lambda *_: self._update_workspace_launchpad_visibility())

        self.workspace_launchpad = WorkspaceLaunchpadWidget(self.mdi_area.viewport())
        self.workspace_launchpad.action_drop_requested.connect(self.handle_launchpad_action_drop)
        self.workspace_launchpad.action_click_requested.connect(self.handle_launchpad_action_click)
        self.workspace_launchpad.hide()
        
        # Title & Menu Container (Full Width above docks)
        self.top_container = QWidget()
        self.top_layout = QVBoxLayout(self.top_container)
        self.top_layout.setContentsMargins(0, 0, 0, 0)
        self.top_layout.setSpacing(0)
        
        # Title Bar
        self.title_bar = ModernTitleBar(self)
        self.top_layout.addWidget(self.title_bar)
        
        self.setMenuWidget(self.top_container)
        
        # Apply Frameless Resizing Helper
        self.resizer = FramelessHelper(self)
        self.resizer.add_widget(self.title_bar)
        self.resizer.add_widget(self.top_container)
        
        self.create_menu()
        self.setup_dock_ui()
        
        # Initialize Header Effects from config
        from scripts.rendering.overlays import HeaderWidget
        HeaderWidget.show_effects = app_config.get_header_effects_enabled()
        
        # AI助手和脚本编辑器改为按需加载
        # 不再在初始化时创建，而是通过插件管理器延迟加载
        
        # Always load the AI plugin during initialization (before show()) to settle OpenGL
        # This prevents flickering when manually opening it later.
        self.load_ai_assistant_plugin()
        
        if self._show_ai_chat:
             # Delay the initial show to let the WebEngine render its background color quietly.
             # This prevents the brief "black flash" during the first paint.
             QTimer.singleShot(1000, self.show_ai_assistant)
        else:
             # Even if not showing, ensure the dock is properly initialized and hidden
             if self._ai_plugin:
                 self._ai_plugin.hide_ai_assistant()
        
        # Theme
        self.apply_theme()
        
        # Simulated Clipboard for Explorer (item_data, operation_type, db_path)
        self.explorer_clipboard = None 
        
        # Install global event filter for "Deselect on Outside Click"
        QApplication.instance().installEventFilter(self)
        
        # Native Shadow (Delayed to ensure winId is ready)
        QTimer.singleShot(100, self._enable_native_shadow)
        QTimer.singleShot(0, self._update_workspace_launchpad_visibility)
    
    def changeEvent(self, event):
        """Handle window state changes (maximize/restore) to toggle borders and corners."""
        if event.type() == QEvent.WindowStateChange:
            is_max = self.isMaximized()
            self.setProperty("maximized", is_max)
            
            # Update native window attributes (corners, shadow)
            self._update_window_flags(is_max)
            
            # Re-apply style to update border
            self.style().unpolish(self)
            self.style().polish(self)
        super().changeEvent(event)

    def _update_window_flags(self, is_max):
        """Toggle DWM attributes based on window state."""
        if sys.platform != 'win32':
            return
        try:
            from ctypes import windll, c_int, byref, Structure
            hWnd = int(self.winId())
            
            # 1. Corner preference: 1 = DONOTROUND (Maximized), 2 = ROUNDED (Normalized)
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            pref = c_int(1 if is_max else 2)
            windll.dwmapi.DwmSetWindowAttribute(hWnd, DWMWA_WINDOW_CORNER_PREFERENCE, byref(pref), 4)
            
            # 2. Reset margins if maximized to avoid weird border artifacts
            class MARGINS(Structure):
                _fields_ = [("cxLeftWidth", c_int), ("cxRightWidth", c_int),
                            ("cyTopHeight", c_int), ("cyBottomHeight", c_int)]
            
            m = -1 if not is_max else 0
            margins = MARGINS(m, m, m, m)
            windll.dwmapi.DwmExtendFrameIntoClientArea(hWnd, byref(margins))
        except:
            pass

    def _enable_native_shadow(self):
        """Enable modern Windows drop shadow and rounded corners for frameless window."""
        if sys.platform != 'win32':
            return
        try:
            from ctypes import windll, c_int, byref, Structure
            
            # MARGINS Structure for DWM
            class MARGINS(Structure):
                _fields_ = [("cxLeftWidth", c_int), ("cxRightWidth", c_int),
                            ("cyTopHeight", c_int), ("cyBottomHeight", c_int)]
            
            hWnd = int(self.winId())
            
            # 1. DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUNDED = 2 (Win 11 Rounded Corners)
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_ROUNDED = 2
            windll.dwmapi.DwmSetWindowAttribute(hWnd, DWMWA_WINDOW_CORNER_PREFERENCE, byref(c_int(DWMWCP_ROUNDED)), 4)
            
            # 2. DWMWA_NCRENDERING_POLICY = 2, DWMNRP_ENABLED = 2 (Enable NC rendering for shadow)
            DWMWA_NCRENDERING_POLICY = 2
            DWMNRP_ENABLED = 2
            windll.dwmapi.DwmSetWindowAttribute(hWnd, DWMWA_NCRENDERING_POLICY, byref(c_int(DWMNRP_ENABLED)), 4)
            
            # 3. Extend Frame to trigger the shadow
            margins = MARGINS(-1, -1, -1, -1)
            windll.dwmapi.DwmExtendFrameIntoClientArea(hWnd, byref(margins))
            
            logger.info("Native Windows shadow and rounded corners enabled.")
        except Exception as e:
            logger.debug(f"Failed to enable modern native shadow: {e}")
    
    def _scan_all_wells(self):
        """扫描 data/ 下所有 .db 文件, 返回 [{'id', 'name', 'db_path'}, ...]"""
        wells = []
        data_dir = "data"
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
            return wells
        for db_file in os.listdir(data_dir):
            if not db_file.endswith(".db"):
                continue
            db_path = os.path.join(data_dir, db_file)
            try:
                temp_db = DBManager(db_path, ensure_schema=False)
                for wid, wname in temp_db.get_wells():
                    wells.append({'id': wid, 'name': wname, 'db_path': db_path})
            except Exception as e:
                logger.error(f"Error loading database {db_file}: {e}")
        return wells
    
    @staticmethod
    def _is_2d_curve(shape) -> bool:
        """判断曲线是否为 2D 数据。"""
        s = str(shape)
        return "," in s and len(s.split(',')) > 1 and s.split(',')[1].strip() != ''

    
    def init_plugin_manager(self):
        """初始化插件管理器（在需要时调用）"""
        if self.plugin_manager is None:
            from core.plugin_interface import PluginManager
            self.plugin_manager = PluginManager(self)
            # 注册插件路径
            plugins_dir = os.path.join(os.path.dirname(__file__), 'plugins')
            self.plugin_manager.register_plugin_path(plugins_dir)
    
    def load_ai_assistant_plugin(self):
        """加载AI助手插件（按需加载）"""
        if self._ai_plugin is not None:
            return self._ai_plugin
            
        self.init_plugin_manager()
        
        try:
            if self.plugin_manager.load_plugin('ai_assistant'):
                self._ai_plugin = self.plugin_manager.get_plugin('ai_assistant')
                if self._ai_plugin:
                    self._ai_plugin.enable()
                    # 不再调用get_menu_actions，因为它返回空列表
                    return self._ai_plugin
        except Exception as e:
            logger.error(f"Failed to load AI Assistant plugin: {e}")
        return None
    
    def load_script_editor_plugin(self):
        """加载脚本编辑器插件（按需加载）"""
        if self._script_plugin is not None:
            return self._script_plugin
            
        self.init_plugin_manager()
        
        try:
            # 直接从文件路径导入ScriptEditorPlugin，避免模块名称冲突
            import importlib.util
            import sys
            import os
            
            plugin_path = os.path.join(os.path.dirname(__file__), 'plugins', 'ai_assistant', 'plugin.py')
            if os.path.exists(plugin_path):
                spec = importlib.util.spec_from_file_location(
                    'ai_assistant_plugin', 
                    plugin_path
                )
                module = importlib.util.module_from_spec(spec)
                sys.modules['ai_assistant_plugin'] = module
                spec.loader.exec_module(module)
                
                if hasattr(module, 'ScriptEditorPlugin'):
                    self._script_plugin = module.ScriptEditorPlugin(self)
                    if self._script_plugin.initialize():
                        # 不再调用get_menu_actions，因为它返回空列表
                        return self._script_plugin
        except Exception as e:
            logger.error(f"Failed to load Script Editor plugin: {e}")
        return None
    
    def show_ai_assistant(self):
        """切换AI助手显示状态"""
        plugin = self.load_ai_assistant_plugin()
        if plugin:
            plugin.toggle_ai_assistant()
        else:
            QMessageBox.warning(self, "插件未加载", "AI助手插件未能成功加载。")
    
    def new_script_window(self):
        """创建新的脚本编辑器窗口（按需加载）"""
        plugin = self.load_script_editor_plugin()
        if plugin:
            db_path = self.db.db_path if self.db else None
            plugin.create_script_editor(db_path)
        else:
            QMessageBox.warning(self, "插件未加载", "脚本编辑器插件未能成功加载。")
    

    def create_menu(self):
        from scripts.ui.menu_manager import MenuManager
        # Create a dedicated QMenuBar as a regular widget
        self.custom_menu_bar = QMenuBar()
        # Instead of adding to top_layout directly, let the title bar handle it
        if hasattr(self, 'title_bar'):
            self.title_bar.set_menu_bar(self.custom_menu_bar)
            
        self.menu_manager = MenuManager(self, self.custom_menu_bar)
        
        # Ensure the whole top container is updated
        self.top_container.update()

    def handle_horizontal_scale(self, factor):
        active_sub = self.mdi_area.activeSubWindow()
        if active_sub:
            widget = active_sub.widget()
            if hasattr(widget, 'set_horizontal_scale'):
                widget.set_horizontal_scale(factor)

    def toggle_explorer(self, checked):
        if hasattr(self, 'explorer_dock'):
            self.explorer_dock.setVisible(checked)

    def toggle_ai(self, checked):
        """切换AI助手显示状态（支持插件化）"""
        if checked:
            self.show_ai_assistant()
        else:
            if self._ai_plugin:
                self._ai_plugin.hide_ai_assistant()
            
    def on_dock_visibility_changed(self):
        # Update menu check states if closed via X button
        if hasattr(self, 'explorer_dock'):
            self.toggle_explorer_action.setChecked(self.explorer_dock.isVisible())

    def toggle_skip_finite_check(self, checked):
        """Apply performance optimization to all open plot windows."""
        for sub in self.mdi_area.subWindowList():
            widget = sub.widget()
            if isinstance(widget, LogWidget):
                widget.set_skip_finite_check(checked)

    def handle_about(self):
        """Show the About dialog."""
        from scripts.ui.dialogs.about_dialog import AboutDialog
        dlg = AboutDialog(self)
        dlg.exec()

    def handle_export_plot(self):
        """Trigger advanced export on the active plot."""
        active_sub = self.mdi_area.activeSubWindow()
        if not active_sub:
            QMessageBox.warning(self, "Export", "Please select a plot window first.")
            return
            
        widget = active_sub.widget()
        if isinstance(widget, LogWidget):
            self.statusBar().showMessage("Exporting ...")
            widget.export_plot()
        else:
            QMessageBox.warning(self, "Export", "Active window is not a Log Plot.")

    def handle_save_template(self):
        active_sub = self.mdi_area.activeSubWindow()
        if not active_sub or not isinstance(active_sub.widget(), LogWidget):
            QMessageBox.warning(self, "Templates", "Please select a plot window first.")
            return
            
        path, _ = QFileDialog.getSaveFileName(self, "Save Plot Template", "data/templates", "PyLog Template (*.plt);;JSON (*.json)")
        if path:
            from scripts.data.template_manager import TemplateManager
            if TemplateManager.save_template(active_sub.widget(), path):
                self.statusBar().showMessage(f"Template saved to {os.path.basename(path)}")
            else:
                QMessageBox.critical(self, "Error", "Failed to save template.")

    def handle_apply_template(self):
        template_dir = os.path.join("data", "templates")
        template_paths = []
        if os.path.isdir(template_dir):
            for name in sorted(os.listdir(template_dir)):
                if name.lower().endswith((".plt", ".json")):
                    template_paths.append(os.path.join(template_dir, name))

        if not template_paths:
            QMessageBox.warning(self, "Templates", "No template files were found in data/templates.")
            return

        wells = self._scan_all_wells()
        
        if not wells:
            QMessageBox.warning(self, "Templates", "No wells found in the data/ folder. Please import data first.")
            return

        from scripts.ui.plot_dialogs import TemplateApplyDialog
        dlg = TemplateApplyDialog(template_paths, wells, self)
        if dlg.exec() != QDialog.Accepted:
            return

        path = dlg.get_selected_template_path()
        selected_well = dlg.get_selected_well()
        if not path:
            return
        if not selected_well:
            return
            
        well_id = selected_well['id']
        db_path = selected_well['db_path']
        template_db = self.db if self.db and getattr(self.db, "db_path", None) == db_path else DBManager(db_path, ensure_schema=False)
        plot_spec = TemplateManager.resolve_template_to_plot_spec(
            template_db,
            path,
            well_id=well_id,
        )
        if not plot_spec.get("tracks"):
            QMessageBox.warning(self, "Warning", "Template applied, but no matching curves were found in the selected well.")
            return

        if not plot_spec.get("title"):
            template_state = TemplateManager.load_template_spec(path)
            if isinstance(template_state, dict):
                plot_spec["title"] = template_state.get("title")

        self.statusBar().showMessage(f"Applying template to {selected_well['name']}...", 3000)
        QTimer.singleShot(
            50,
            lambda: open_plot_from_spec(self, plot_spec),
        )

    def toggle_antialias(self, checked):
        """Toggle antialias globally."""
        import pyqtgraph as pg
        pg.setConfigOptions(antialias=checked)

    def setup_dock_ui(self):
        self.explorer = UnifiedExplorer(self)
        self.tree = self.explorer.data_tree # Compatibility reference
        
        # Initialize TreeController to handle all tree CRUD operations
        from scripts.ui.tree_controller import TreeController
        self.tree_controller = TreeController(self)
        
        # Connect signals — delegate tree operations to TreeController
        self.tree.customContextMenuRequested.connect(self.tree_controller.show_context_menu)
        self.tree.itemDoubleClicked.connect(self.handle_tree_item_double_clicked)
        self.tree.item_loading_requested.connect(self.tree_controller.load_children_for_item)
        self.tree.itemSelectionChanged.connect(self.on_explorer_selection_changed)
        
        # [NEW] Script Tree Logic
        self.explorer.script_tree.itemDoubleClicked.connect(self.handle_script_double_clicked)
        self.explorer.script_tree.script_open_requested.connect(self.open_script_file)
        self.explorer.script_tree.file_preview_requested.connect(self.open_html_preview)
        
        self.explorer_dock = QDockWidget("Explorer", self)
        self.explorer_dock.setWidget(self.explorer)
        
        # Hide default title bar
        self.explorer_dock.setTitleBarWidget(QWidget()) 
        
        self.explorer_dock.visibilityChanged.connect(self.on_dock_visibility_changed)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.explorer_dock)
        
        # [NEW] 设置左侧浏览器浏览器的初始默认宽度
        self.resizeDocks([self.explorer_dock], [320], Qt.Horizontal)
        
        self.tree_controller.populate_tree()

    def on_explorer_selection_changed(self):
        """处理资源管理器选择变化（支持插件化）"""
        if not hasattr(self, 'tree'):
            return

        items_data = []
        for item in self.tree.selectedItems():
            d = item.data(0, Qt.UserRole)
            if not isinstance(d, dict):
                continue
            dd = dict(d)
            dd['name'] = item.text(0)  # 添加name字段用于上下文传递
            dd['display_name'] = item.text(0)
            
            breadcrumbs = []
            if 'db_path' in dd:
                breadcrumbs.append({"type": "database", "name": dd['db_path']})
            
            well_name = None
            parent = item.parent()
            if parent:
                p_data = parent.data(0, Qt.UserRole)
                if isinstance(p_data, dict):
                    if p_data.get('type') == 'folder':
                        dd['folder_name'] = parent.text(0)
                        # Root well name for folders is the grand-parent (usually)
                        grand_parent = parent.parent()
                        if grand_parent and grand_parent.data(0, Qt.UserRole).get('type') == 'well':
                            well_name = grand_parent.text(0).replace("Well: ", "")
                    elif p_data.get('type') == 'well':
                        well_name = parent.text(0).replace("Well: ", "")
            
            if well_name:
                dd['well_name'] = well_name
                breadcrumbs.append({"type": "well", "name": well_name})
            
            breadcrumbs.append({"type": dd.get('type', 'item'), "name": item.text(0)})
            
            attributes = []
            if item.text(1): attributes.append({"label": "Type/Size", "value": item.text(1)})
            if item.text(2): attributes.append({"label": "Unit", "value": item.text(2)})
            if 'db_path' in dd: attributes.append({"label": "Path", "value": dd['db_path']})
            if well_name: attributes.append({"label": "Well Name", "value": well_name})
            if 'id' in dd: attributes.append({"label": "ID", "value": dd['id']})
            if 'well_id' in dd: attributes.append({"label": "Well ID", "value": dd['well_id']})
            
            # [NEW] Add data range for curves if cached
            if dd.get('type') == 'curve' and 'min' in dd and 'max' in dd:
                vmin, vmax = dd['min'], dd['max']
                if vmin is not None and vmax is not None:
                    attributes.append({"label": "Range", "value": f"{vmin:.2f} - {vmax:.2f}"})

            dd['breadcrumbs'] = breadcrumbs
            dd['attributes'] = attributes
            
            items_data.append(dd)
        
        # 发送信号给AI助手插件（如果已加载）
        if self._ai_plugin:
            try:
                self._ai_plugin.on_selection_changed(items_data)
            except Exception:
                pass

    # --- Tree CRUD operations delegated to TreeController ---
    # (see scripts/ui/tree_controller.py)
    
    def populate_tree(self):
        """Delegate to TreeController for tree population."""
        self.tree_controller.populate_tree()


    def handle_tree_item_double_clicked(self, item, column):
        data = item.data(0, Qt.UserRole)
        if not data or data.get('type') != 'curve':
            return
            
        curve_id = data['id']
        well_id = data['well_id']
        db_p = data['db_path']

        # [NEW] Double-click unit to Rename Unit
        if column == 2:
            current_unit = item.text(2)
            dlg = UnitEditDialog(item.text(0), current_unit, self)
            if dlg.exec() == QDialog.Accepted:
                new_unit = dlg.get_unit()
                if DBManager(db_p).update_curve_unit(curve_id, new_unit):
                    item.setText(2, new_unit)
                    self.statusBar().showMessage(f"Unit updated to: {new_unit}", 3000)
                else:
                    QMessageBox.critical(self, "Error", "Failed to update unit in database.")
            return
        
        well_name = "Unknown Well"
        if item.parent():
            well_name = item.parent().text(0).replace("Well: ", "")
            
        widget = self.new_data_viewer_window()
        if not widget:
            return
        widget.add_curve_request(well_id, curve_id, db_p, well_name=well_name, curve_name=item.text(0))

    def handle_quick_plot(self, items_data, title=None):
        """Create a new plot window and add all selected curves to it."""
        plot_spec = build_plot_spec_from_manual_items(
            items_data,
            title=title or f"Log Plot {getattr(self, '_plot_count', 0) + 1}",
        )
        widget, added_count = open_plot_from_spec(self, plot_spec)
        if widget:
            widget._snapshot_reason = "manual"
            widget._snapshot_logged = False
            widget._trace_enabled = True
            widget._trace_seq = 0
            self.statusBar().showMessage(f"Quick Plot: {added_count} curves added.", 3000)

    def handle_open_data_viewer(self, items_data):
        """Open a data viewer page and enqueue selected curves."""
        curves = [d for d in items_data if d.get('type') == 'curve']
        if not curves:
            return

        widget = self.new_data_viewer_window()
        if not widget:
            return

        for curve in curves:
            widget.add_curve_request(
                curve.get('well_id'),
                curve.get('id'),
                curve.get('db_path'),
                well_name=curve.get('well_name'),
                curve_name=curve.get('name'),
            )

        self.statusBar().showMessage(f"Data Viewer: queued {len(curves)} curves.", 3000)

    def handle_launchpad_plot_drop(self, curves):
        if not curves:
            return
        items_data = []
        for curve in curves:
            curve_id = curve.get("curve_id", curve.get("id"))
            if curve_id is None:
                continue
            items_data.append({
                "type": "curve",
                "id": curve_id,
                "well_id": curve.get("well_id"),
                "db_path": curve.get("db_path"),
                "name": curve.get("name"),
            })

        plot_spec = build_plot_spec_from_manual_items(
            items_data,
            title=f"Log Plot {getattr(self, '_plot_count', 0) + 1}",
        )
        widget, added_count = open_plot_from_spec(self, plot_spec)
        if widget:
            widget._snapshot_reason = "manual"
            widget._snapshot_logged = False
            widget._trace_enabled = True
            widget._trace_seq = 0
            self.statusBar().showMessage(f"Launchpad Plot: added {added_count} curve(s).", 3000)

    def handle_launchpad_data_viewer_drop(self, curves):
        if not curves:
            return
        widget = self.new_data_viewer_window()
        if not widget:
            return
        for curve in curves:
            widget.add_curve_request(curve.get("well_id"), curve.get("curve_id"), curve.get("db_path"))
        self.statusBar().showMessage(f"Launchpad Data Viewer: queued {len(curves)} curve(s).", 3000)

    def handle_launchpad_action_click(self, action_key):
        if action_key == "plot":
            self.new_plot_window()
        elif action_key == "data_viewer":
            self.new_data_viewer_window()

    def handle_launchpad_action_drop(self, action_key, curves):
        if action_key == "plot":
            self.handle_launchpad_plot_drop(curves)
        elif action_key == "data_viewer":
            self.handle_launchpad_data_viewer_drop(curves)

    def handle_script_double_clicked(self, item, column):
        """Open a script in a new script editor window."""
        data = item.data(0, Qt.UserRole)
        if not data or data.get('type') not in {'script', 'file'}:
            return
            
        path = data.get('path')
        if is_html_previewable(path):
            self.open_html_preview(path)
            return
        self.open_script_file(path)

    def open_html_preview(self, path):
        """Open a local HTML file in a dedicated workspace preview."""
        if not path or not os.path.exists(path) or not is_html_previewable(path):
            return

        abs_path = os.path.abspath(path)
        for sub in self.mdi_area.subWindowList():
            widget = sub.widget()
            if getattr(widget, "html_preview_path", None) == abs_path:
                self.mdi_area.setActiveSubWindow(sub)
                if hasattr(widget, "load_file"):
                    widget.load_file(abs_path)
                sub.show()
                return

        widget = HtmlPreviewWidget(abs_path, self)
        widget.html_preview_path = abs_path
        widget.openSourceRequested.connect(self.open_script_file)

        sub = QMdiSubWindow()
        sub.setWidget(widget)
        sub.setAttribute(Qt.WA_DeleteOnClose)
        sub.setWindowTitle(f"HTML: {os.path.basename(path)}")
        sub.setWindowIcon(self.style().standardIcon(QStyle.SP_FileIcon))
        sub.destroyed.connect(lambda: QTimer.singleShot(0, self.check_reset_counters))

        self.mdi_area.addSubWindow(sub)
        sub.show()
        self.mdi_area.setActiveSubWindow(sub)
        self._update_workspace_launchpad_visibility()
    
    def open_script_file(self, path):
        """Open a script file in a new script editor window."""
        if not path:
            return
            
        # Normalize path
        abs_path = os.path.abspath(path)
        
        # Check if already open
        for sub in self.mdi_area.subWindowList():
            editor = sub.widget()
            if hasattr(editor, 'script_path') and editor.script_path:
                if os.path.abspath(editor.script_path) == abs_path:
                    self.mdi_area.setActiveSubWindow(sub)
                    return
            # Also check window title as fallback or for unsaved/named scripts
            elif sub.windowTitle().endswith(os.path.basename(path)):
                 # Double check if it's actually the same file if possible, or just trust the path match above
                 pass

        if not os.path.exists(path):
            return
            
        # Read script content first
        try:
            with open(path, 'r', encoding='utf-8') as f:
                script_content = f.read()
        except Exception as e:
            return
            
        # Create new window
        self.new_script_window()
        active_sub = self.mdi_area.activeSubWindow()
        if active_sub:
            editor = active_sub.widget()
            try:
                if hasattr(editor, 'set_code'):
                    editor.set_code(script_content)
                    editor.script_path = path # Set path property
                    active_sub.setWindowTitle(f"Script: {os.path.basename(path)}")
            except Exception:
                pass

    @qasync.asyncSlot()
    async def handle_import_dlis(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Import DLIS File", "", "DLIS Files (*.dlis);;All Files (*)")
        if file_name:
            # 1. Quick Meta-Analysis
            self.statusBar().showMessage("Analyzing DLIS metadata...")
            QApplication.setOverrideCursor(Qt.WaitCursor)
            # [TODO] get_dlis_info could also be async if needed, but it's usually fast enough
            info = get_dlis_info(file_name)
            QApplication.restoreOverrideCursor()
            
            if not info['curves']:
                QMessageBox.warning(self, "Import Error", "No data channels found in this DLIS file.")
                return

            # 2. Show Custom Selection Dialog
            dlg = DLISImportDialog(info['well_name'], info['curves'], self)
            if dlg.exec() != QDialog.Accepted:
                self.statusBar().showMessage("Import cancelled.", 3000)
                return

            well_name, selected_curves = dlg.get_settings()
            
            # 3. Launch Import Worker
            self.statusBar().showMessage(f"Preparing to import {len(selected_curves)} curves to '{well_name}'...")
            QApplication.processEvents()
            
            self.import_action.setEnabled(False)
            self.worker = ImportWorker(file_name, custom_well_name=well_name, selected_curves=selected_curves)
            
            # Connect signals for UI updates (progress only)
            if hasattr(self, 'on_curve_imported'):
                self.worker.curve_signal.connect(self.on_curve_imported)
            
            # Direct await for completion
            well_id = await self.worker.run_async()
            
            # Handle result
            self.on_import_finished(well_id)

    def handle_export_dlis(self):
        wells = self.get_all_well_info()
        if not wells:
            ThemeDialog.message(self, "Export DLIS", "No wells found in the data/ folder. Please import data first.", icon_type="warning")
            return

        dlg = DLISExportDialog(wells, self)
        dlg.set_export_request_handler(self._run_dlis_export_from_dialog)
        for well in wells:
            try:
                db = DBManager(well["db_path"])
                snapshot = get_well_export_snapshot(db, well["db_path"], well["id"])
                dlg.set_well_snapshot(well["db_path"], well["id"], snapshot)
            except Exception as exc:
                logger.error(f"Failed to prepare DLIS export snapshot for {well.get('name')}: {exc}")

        if dlg.exec() != QDialog.Accepted:
            self.statusBar().showMessage("DLIS export cancelled.", 3000)
            return

    def _run_dlis_export_from_dialog(self, settings, dlg):
        selected_well = settings["well"]
        output_path = settings["output_path"]
        selected_curves = settings["curves"]

        try:
            db = DBManager(selected_well["db_path"])
            snapshot = get_well_export_snapshot(db, selected_well["db_path"], selected_well["id"])
            self.export_worker = ExportWorker(
                {
                    "db_path": selected_well["db_path"],
                    "well_id": selected_well["id"],
                    "well_name": selected_well["name"],
                    "snapshot": snapshot,
                },
                selected_curves,
                output_path,
            )
            self.export_worker.progress.connect(lambda payload: self._handle_export_progress(payload, dlg, output_path))
            result = asyncio.create_task(self.export_worker.run_async())
        except Exception as exc:
            dlg.finish_export()
            logger.error(f"DLIS export failed: {exc}")
            ThemeDialog.message(self, "Export DLIS", f"Failed to export DLIS file:\n{exc}", icon_type="error")
            return

        async def finalize_export():
            export_result = await result
            dlg.finish_export()
            self._complete_export_dialog(export_result, dlg, output_path)

        asyncio.create_task(finalize_export())

    def _handle_export_progress(self, payload, dlg, output_path):
        phase = payload.get("phase")
        curve_name = payload.get("curve") or "Unknown"
        dlg.update_export_progress(payload)
        if phase == "preparing_curve":
            total = max(int(payload.get("total") or 0), 1)
            current = min(int(payload.get("current") or 0), total)
            self.statusBar().showMessage(f"Preparing DLIS curve {current}/{total}: {curve_name}")
        elif phase == "writing_file":
            self.statusBar().showMessage(f"Exporting DLIS: writing file {os.path.basename(output_path)}...")
        elif phase == "writing_records":
            total = max(int(payload.get("total") or 0), 1)
            current = min(int(payload.get("current") or 0), total)
            self.statusBar().showMessage(f"Writing DLIS records {current}/{total}")
        else:
            self.statusBar().showMessage(f"Exporting DLIS: writing file {os.path.basename(output_path)}...")

    def _complete_export_dialog(self, result, dlg, output_path):
        if not result:
            ThemeDialog.message(self, "Export DLIS", "Failed to export DLIS file.", icon_type="error")
            return

        if not result.get("ok"):
            detail = result.get("action_hint")
            message = result.get("error", "Failed to export DLIS file.")
            if detail:
                message = f"{message}\n\n{detail}"
            ThemeDialog.message(self, "Export DLIS", message, icon_type="warning")
            return

        self.statusBar().showMessage(f"DLIS export complete: {output_path}", 5000)
        dlg.set_export_summary(f"Export complete: {result.get('exported_curve_count', 0)} curves exported.")
        dlg.accept()
        DLISExportResultDialog("Export DLIS", output_path, result, self).exec()

    def on_curve_imported(self, curve_name):
        self.statusBar().showMessage(f"Importing: {curve_name}...")

    def on_import_finished(self, well_id):
        self.import_action.setEnabled(True)
        if well_id:
            self.populate_tree()
            self.statusBar().showMessage("Import successful.", 5000)
            QMessageBox.information(self, "Success", "Imported DLIS file successfully.")
        else:
            self.statusBar().showMessage("Import failed.", 5000)
            QMessageBox.warning(self, "Error", "Failed to import DLIS file.")

    def on_import_error(self, error_msg):
        self.import_action.setEnabled(True)
        self.statusBar().showMessage(f"Import error: {error_msg}", 5000)
        QMessageBox.critical(self, "Error", f"An error occurred: {error_msg}")

    def get_active_db(self):
        """Ensure self.db is initialized by falling back to the first available data/ DB."""
        if self.db:
            return self.db
            
        data_dir = "data"
        if os.path.exists(data_dir):
            db_files = [f for f in os.listdir(data_dir) if f.endswith(".db")]
            if db_files:
                db_path = os.path.join(data_dir, db_files[0])
                self.db = DBManager(db_path)
                return self.db
        return None

    def get_all_well_info(self):
        """Scan all DB files in data/ and return a list of (well_name, db_path, well_id)."""
        return self._scan_all_wells()
        
    def handle_plot_selection(self, metadata_list):
        """[NEW] Forward plot selection metadata to the AI plugin."""
        self.plot_selection_changed.emit(metadata_list)


    def new_plot_window(self):
        # Counter for unique titles
        if not hasattr(self, '_plot_count'):
            self._plot_count = 0
        self._plot_count += 1
        
        plot = LogWidget(self.db if self.db else None)
        # [NEW] Connect selection signaling
        plot.selectionChanged.connect(self.handle_plot_selection)
        
        # Apply current optimization states to new window
        plot.set_skip_finite_check(self.skip_finite_action.isChecked())
        
        sub = QMdiSubWindow()
        sub.setWidget(plot)
        sub.setAttribute(Qt.WA_DeleteOnClose)
        
        # Set Icon and Title
        sub.setWindowTitle(f"Log Plot {self._plot_count}")
        # sub.setWindowIcon(self.style().standardIcon(QStyle.SP_DesktopIcon)) # Screen/Plot icon (Monitor)
        
        # Connect destroyed signal to check if we need to reset counter
        sub.destroyed.connect(lambda: QTimer.singleShot(0, self.check_reset_counters))
        
        self.mdi_area.addSubWindow(sub)
        sub.show()
        self._update_workspace_launchpad_visibility()
        return plot

    def new_data_viewer_window(self):
        if not hasattr(self, '_data_viewer_count'):
            self._data_viewer_count = 0
        self._data_viewer_count += 1

        widget = DataViewerWidget()
        sub = QMdiSubWindow()
        sub.setWidget(widget)
        sub.setAttribute(Qt.WA_DeleteOnClose)
        sub.setWindowTitle(f"Data Viewer {self._data_viewer_count}")
        sub.resize(420, 520)
        sub.destroyed.connect(lambda: QTimer.singleShot(0, self.check_reset_counters))
        self.mdi_area.addSubWindow(sub)
        sub.show()
        self._update_workspace_launchpad_visibility()
        return widget

    def new_script_window(self):
        # Counter for unique titles
        if not hasattr(self, '_script_count'):
            self._script_count = 0
        self._script_count += 1
        
        # 使用插件创建脚本编辑器
        plugin = self.load_script_editor_plugin()
        if plugin:
            editor = plugin.create_script_editor(self.get_active_db())
            if editor:
                sub = QMdiSubWindow()
                sub.setWidget(editor)
                sub.setAttribute(Qt.WA_DeleteOnClose)
                
                # Set Icon and Title
                sub.setWindowTitle(f"Script {self._script_count}")
                sub.setWindowIcon(self.style().standardIcon(QStyle.SP_FileIcon)) # File/Code icon
                
                # Connect destroyed signal to check if we need to reset counter
                sub.destroyed.connect(lambda: QTimer.singleShot(0, self.check_reset_counters))
                
                # Connect script_saved signal to refresh script list
                if hasattr(editor, 'script_saved'):
                    editor.script_saved.connect(self.on_script_saved)
                
                self.mdi_area.addSubWindow(sub)
                sub.show()
                self._update_workspace_launchpad_visibility()

    def on_script_saved(self, filepath):
        """Handle script saved event - refresh script list in explorer"""
        if hasattr(self, 'explorer') and self.explorer:
            # 如果当前在 SCRIPTS 视图，刷新脚本列表
            if self.explorer.stack.currentIndex() == 1:
                self.explorer.populate_scripts()

    def check_reset_counters(self):
        """Check if all windows of a type are closed, and if so, reset the counter."""
        plots = [w for w in self.mdi_area.subWindowList() if isinstance(w.widget(), LogWidget)]
        data_viewers = [w for w in self.mdi_area.subWindowList() if isinstance(w.widget(), DataViewerWidget)]
        
        # 延迟导入WebScriptEditor以支持插件化
        try:
            from plugins.ai_assistant.ui.widgets.web_script_editor import WebScriptEditor
            scripts = [w for w in self.mdi_area.subWindowList() if isinstance(w.widget(), WebScriptEditor)]
        except ImportError:
            scripts = []
        
        if not plots:
            self._plot_count = 0

        if not data_viewers:
            self._data_viewer_count = 0
            
        if not scripts:
            self._script_count = 0
        self._update_workspace_launchpad_visibility()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "workspace_launchpad") and self.workspace_launchpad:
            self.workspace_launchpad.setGeometry(self.mdi_area.viewport().rect())

    def showEvent(self, event):
        super().showEvent(event)
        self._update_workspace_launchpad_visibility()

    def _update_workspace_launchpad_visibility(self):
        if not hasattr(self, "workspace_launchpad") or not self.workspace_launchpad:
            return
        self.workspace_launchpad.setGeometry(self.mdi_area.viewport().rect())
        has_subwindows = bool(self.mdi_area.subWindowList())
        self.workspace_launchpad.setVisible(not has_subwindows)
        if not has_subwindows:
            self.workspace_launchpad.raise_()

    def apply_theme(self, theme_name=None):
        if theme_name is not None:
            app_config.set_theme_name(theme_name)
        
        from scripts.ui.theme_manager import ThemeManager
        ThemeManager.apply_to_main_window(self, theme_name)
        
        if hasattr(self, 'title_bar'):
            self.title_bar.update_theme()
            bg = app_config.get_theme_color("bg_pure")
            self.top_container.setStyleSheet(f"background-color: {bg}; border: none;")
        
        # [NEW] Re-apply style to all open dock widgets and toolbars
        for dock in self.findChildren(QDockWidget):
            dock.update()

        # [NEW] Update AI Assistant and Script Editors
        theme = (theme_name or app_config.get_theme_name()).lower()
        
        # 1. Update AI Assistant
        if hasattr(self, '_ai_plugin') and self._ai_plugin:
            if hasattr(self._ai_plugin, 'ai_widget') and self._ai_plugin.ai_widget:
                if hasattr(self._ai_plugin.ai_widget, 'set_theme'):
                    self._ai_plugin.ai_widget.set_theme(theme)
        
        # 2. Update all open Script Editors
        try:
            from plugins.ai_assistant.ui.widgets.web_script_editor import WebScriptEditor
            for sub in self.mdi_area.subWindowList():
                widget = sub.widget()
                if isinstance(widget, WebScriptEditor):
                    widget.set_theme(theme)
        except ImportError:
            pass

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress:
            # Skip global deselection if Ctrl/Shift is pressed (multi-selection mode)
            if event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
                return super().eventFilter(obj, event)

            is_clamped_to_plot = False
            
            # [NEW] More robust check: is the object or any of its parents a LogWidget?
            curr = obj
            while curr:
                if isinstance(curr, LogWidget):
                    is_clamped_to_plot = True
                    break
                curr = curr.parent()
            
            if not is_clamped_to_plot:
                # [FALLBACK] Global geometry check
                try:
                    g_pos = event.globalPosition().toPoint()
                except AttributeError:
                    g_pos = event.globalPos()
                    
                for sub in self.mdi_area.subWindowList():
                    plot = sub.widget()
                    if isinstance(plot, LogWidget):
                        if plot.isVisible() and plot.rect().contains(plot.mapFromGlobal(g_pos)):
                            is_clamped_to_plot = True
                            break
            
            # Also skip if it's a dialog (e.g. tracks settings)
            if not is_clamped_to_plot:
                curr = obj
                while curr:
                    if isinstance(curr, QDialog):
                        is_clamped_to_plot = True
                        break
                    curr = curr.parent()
            
            if not is_clamped_to_plot:
                # Clicking globally outside -> Deselect all plots
                for sub in self.mdi_area.subWindowList():
                    plot = sub.widget()
                    if isinstance(plot, LogWidget):
                        plot.deselect_all_tracks()
                        
        return super().eventFilter(obj, event)

    def toggle_effects(self, checked):
        """Toggles high-end visual effects (like frosted glass) globally."""
        from scripts.rendering.overlays import HeaderWidget
        HeaderWidget.show_effects = checked
        
        # Save to config
        app_config.set_header_effects_enabled(checked)
        
        # Trigger repaint for all open plot windows
        for sub in self.mdi_area.subWindowList():
            plot = sub.widget()
            if hasattr(plot, 'track_containers'):
                for track in plot.track_containers:
                    if hasattr(track, 'header'):
                        track.header.update()

if __name__ == "__main__":
    logger.info("Starting PyLog Application...")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Use qasync to bridge asyncio and Qt
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    
    window = MainWindow()
    window.show()

    # 此时不需要再连接 aboutToQuit 信号了
    # app.aboutToQuit.connect(...) 

    try:
        with loop:
            # 1. Start the event loop
            loop.run_forever()
            
            # ---------------------------------------------------------
            # 2. After loop.run_forever() returns, perform cleanup.
            # ---------------------------------------------------------
            try:
                # Safely get the singleton manager
                try:
                    from plugins.ai_assistant.ai_core.mcp_client import MCPClientManager
                    mcp_manager = MCPClientManager()
                except ImportError:
                    mcp_manager = None
                
                if mcp_manager and hasattr(mcp_manager, 'sessions') and mcp_manager.sessions:
                    logger.info(f"Shutting down {len(mcp_manager.sessions)} MCP sessions...")
                    try:
                        # [FINAL FIX] Silence AnyIO's late-running callbacks that cause RuntimeError during teardown
                        def silent_handler(loop, context):
                            msg = context.get('message', '')
                            if 'no running event loop' in msg or 'deliver_cancellation' in str(context):
                                return
                            loop.default_exception_handler(context)
                        
                        old_handler = loop.get_exception_handler()
                        loop.set_exception_handler(silent_handler)
                        
                        try:
                            # Execute async shutdown with a strict 2-second timeout
                            loop.run_until_complete(asyncio.wait_for(mcp_manager.shutdown(), timeout=2.0))
                            # Wait a tiny bit more for AnyIO internal cancellation callbacks to finish
                            loop.run_until_complete(asyncio.sleep(0.1))
                        finally:
                            loop.set_exception_handler(old_handler)
                            
                        logger.info("MCP cleanup finished successfully.")
                    except asyncio.TimeoutError:
                        logger.warning("MCP cleanup timed out!")
                    except Exception as e:
                        logger.error(f"Error during MCP cleanup: {e}")
                
                # ---------------------------------------------------------
                # 2. Force cancel all other pending tasks (Avoid terminal warnings)
                # ---------------------------------------------------------
                pending = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task(loop)]
                if pending:
                    for task in pending:
                        task.cancel()
                    # Give them a moment to cancel
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Application error: {e}")
