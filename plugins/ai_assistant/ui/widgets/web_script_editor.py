
import os
import json
import uuid
import hashlib
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import QUrl, QObject, Slot, Signal, Qt, QSize
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QToolBar, QSplitter, 
                               QPlainTextEdit, QApplication, QInputDialog, QFileDialog)
from PySide6.QtGui import QFont, QAction
from scripts.ui.base_dialog import ThemeDialog

class LoggedPage(QWebEnginePage):
    """Custom QWebEnginePage to forward JS console messages to Python logger."""
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        from scripts.utils.logger import logger
        level_map = {
            QWebEnginePage.InfoMessageLevel: "INFO",
            QWebEnginePage.WarningMessageLevel: "WARNING",
            QWebEnginePage.ErrorMessageLevel: "ERROR"
        }
        lvl_name = level_map.get(level, "DEBUG")
        logger.debug(f"AceEditor JS [{lvl_name}] ({sourceID}:{lineNumber}): {message}")

class WebEditorBridge(QObject):
    """Bridge for JavaScript (Ace Editor) to call Python."""
    textChanged = Signal(str)
    selectionChanged = Signal(str, int, int, str) # text, x, y, lineStr
    previewAccepted = Signal()
    
    def __init__(self, initial_content="", parent=None):
        super().__init__(parent)
        self._content = initial_content
        
    @Slot(result=str)
    def getInitialContent(self):
        return self._content

    @Slot(str)
    def onTextChanged(self, text):
        self._content = text
        self.textChanged.emit(text)

    @Slot(str, int, int, str)
    def onSelectionChanged(self, text, x, y, lineStr):
        self.selectionChanged.emit(text, x, y, lineStr)

    @Slot()
    def onPreviewAccepted(self):
        self.previewAccepted.emit()

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QTextEdit, QLabel, QPushButton, 
                               QHBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget)
import numpy as np
import inspect


class VariableInspectorDialog(ThemeDialog):
    def __init__(self, name, value, parent=None):
        import numpy as np
        super().__init__(parent)
        self.setWindowTitle(f"Variable Inspector - {name}")
        self.resize(850, 650)
        
        # UI layout
        self.main_layout = QVBoxLayout()
        self.setLayout(self.main_layout)
        self.main_layout.setContentsMargins(15, 15, 15, 15)
        self.main_layout.setSpacing(12)
        
        # Tab Widget
        self.tabs = QTabWidget()
        self.main_layout.addWidget(self.tabs)
        
        # 1. Summary View
        summary_page = QWidget()
        summary_layout = QVBoxLayout(summary_page)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        
        self.content_edit = QTextEdit()
        self.content_edit.setReadOnly(True)
        
        is_table_compatible = False
        
        if isinstance(value, np.ndarray):
            try:
                info = [
                    f"Name:        {name}",
                    f"Type:        NumPy Array",
                    f"Shape:       {value.shape}",
                    f"DataType:    {value.dtype}",
                    f"Size:        {value.size}",
                    f"Dimensions:  {value.ndim}",
                    "-" * 40,
                    f"Min:         {np.min(value) if value.size > 0 else 'N/A'}",
                    f"Max:         {np.max(value) if value.size > 0 else 'N/A'}",
                    f"Mean:        {np.mean(value) if value.size > 0 else 'N/A'}",
                    f"Std Dev:     {np.std(value) if value.size > 0 else 'N/A'}",
                ]
                self.content_edit.setPlainText("\n".join(info))
                is_table_compatible = True
            except Exception as e:
                self.content_edit.setPlainText(f"Error Analyzing Array: {e}")
        elif isinstance(value, (list, dict, set)):
            try:
                formatted = json.dumps(value, indent=4, ensure_ascii=False, default=str)
                self.content_edit.setPlainText(formatted)
                if isinstance(value, list) and len(value) > 0:
                    is_table_compatible = True
            except:
                self.content_edit.setPlainText(str(value))
        else:
            self.content_edit.setPlainText(str(value))
            
        summary_layout.addWidget(self.content_edit)
        self.tabs.addTab(summary_page, "Summary")
        
        # 2. Table View (Grid View)
        if is_table_compatible:
            table_page = QWidget()
            table_layout = QVBoxLayout(table_page)
            table_layout.setContentsMargins(0, 0, 0, 0)
            
            table = QTableWidget()
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            
            if isinstance(value, np.ndarray):
                if value.ndim == 1:
                    max_rows = min(value.size, 2000)
                    table.setRowCount(max_rows)
                    table.setColumnCount(1)
                    table.setHorizontalHeaderLabels(["Value"])
                    for i in range(max_rows):
                        item = QTableWidgetItem(str(value[i]))
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        table.setItem(i, 0, item)
                elif value.ndim >= 2:
                    rows = min(value.shape[0], 1000)
                    cols = min(value.shape[1], 200)
                    table.setRowCount(rows)
                    table.setColumnCount(cols)
                    table.setHorizontalHeaderLabels([str(i) for i in range(cols)])
                    for r in range(rows):
                        for c in range(cols):
                            val_item = value[r, c]
                            item = QTableWidgetItem(str(val_item))
                            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                            table.setItem(r, c, item)
                
                table.verticalHeader().setDefaultSectionSize(28)
                table.verticalHeader().setMinimumSectionSize(20)
                
            elif isinstance(value, list):
                max_list = min(len(value), 2000)
                table.setRowCount(max_list)
                table.setColumnCount(1)
                table.setHorizontalHeaderLabels(["Value"])
                for i in range(max_list):
                    table.setItem(i, 0, QTableWidgetItem(str(value[i])))
            
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
            table.horizontalHeader().setDefaultSectionSize(100)
            table.setAlternatingRowColors(True)
            table_layout.addWidget(table)
            self.tabs.addTab(table_page, "Data Table")
            self.tabs.setCurrentIndex(1)
            
        # 3. Footer Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        copy_btn = QPushButton("📋 Copy Summary")
        copy_btn.clicked.connect(self.copy_to_clipboard)
        
        close_btn = QPushButton("Close")
        close_btn.setObjectName("closeBtn")
        close_btn.clicked.connect(self.accept)
        
        btn_layout.addStretch()
        btn_layout.addWidget(copy_btn)
        btn_layout.addWidget(close_btn)
        self.main_layout.addLayout(btn_layout)

    def copy_to_clipboard(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.content_edit.toPlainText())


class WebScriptEditor(QWidget):
    script_saved = Signal(str)  # 保存成功信号，参数为保存的文件路径
    
    def __init__(self, db_or_path=None, initial_code="", parent=None):
        super().__init__(parent)
        self.db_path = None
        self.db = None
        
        if db_or_path:
            # 检查是否已经是DBManager对象
            if hasattr(db_or_path, 'db_path'):
                # 已经是DBManager对象，直接使用
                self.db = db_or_path
                self.db_path = db_or_path.db_path
            else:
                # 是数据库路径，创建新的DBManager
                self.db_path = db_or_path
                from scripts.data.db_manager import DBManager
                self.db = DBManager(db_or_path)
        
        self.script_path = None # Store the path if opened from/saved to a file
        self.editor_id = str(uuid.uuid4())
        self._preview_original_code = None
        self._preview_source = "none"
        
        # Theme and JS state
        self._current_theme = "light"
        self._is_ready = False
        self._pending_scripts = []
        
        # Timer for debouncing code updates
        from PySide6.QtCore import QTimer
        self._pending_code_timer = QTimer(self)
        self._pending_code_timer.setSingleShot(True)
        self._pending_code_timer.timeout.connect(self.set_pending_code)
        
        # Persistent execution context for Variable Explorer
        self.execution_context = {}
        self._init_execution_context()
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # Toolbar
        self.toolbar = QToolBar()
        self.toolbar.setIconSize(QSize(16, 16))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.layout.addWidget(self.toolbar)
        
        run_action = QAction("Run", self)
        run_action.setShortcut("Ctrl+R")
        run_action.triggered.connect(self.run_code)
        self.toolbar.addAction(run_action)
        
        comment_action = QAction("Comment", self)
        comment_action.setShortcut("Ctrl+/")
        comment_action.triggered.connect(self.comment_code)
        self.toolbar.addAction(comment_action)

        self.toolbar.addSeparator()

        format_action = QAction("Format", self)
        format_action.triggered.connect(self.format_code)
        self.toolbar.addAction(format_action)

        self.toolbar.addSeparator()

        chat_shortcut = QAction("AI Chat", self)
        chat_shortcut.setShortcut("Ctrl+L")
        chat_shortcut.triggered.connect(lambda: self.trigger_ai_action("", use_context=True))
        self.addAction(chat_shortcut) # Add to widget for shortcut to work
        
        # Add a spacer to push subsequent actions to the right
        from PySide6.QtWidgets import QWidget, QSizePolicy
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.toolbar.addWidget(spacer)

        save_action = QAction("Save", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_code)
        self.toolbar.addAction(save_action)
        
        save_as_action = QAction("Save As...", self)
        save_as_action.triggered.connect(self.save_as)
        self.toolbar.addAction(save_as_action)

        # Preview Bar Overlay
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton
        self.preview_bar = QFrame(self)
        # Styles applied in update_theme_styles()
        preview_layout = QHBoxLayout(self.preview_bar)
        preview_layout.setContentsMargins(10, 4, 10, 4)
        preview_label = QLabel("🔔 AI Proposed Changes (Preview Mode)")
        preview_label.setStyleSheet("color: #856404; font-weight: 500;")
        accept_btn = QPushButton("Accept", objectName="acceptBtn")
        reject_btn = QPushButton("Reject", objectName="rejectBtn")
        preview_layout.addWidget(preview_label)
        preview_layout.addStretch()
        preview_layout.addWidget(accept_btn)
        preview_layout.addWidget(reject_btn)
        self.layout.addWidget(self.preview_bar)
        self.preview_bar.hide()
        
        accept_btn.clicked.connect(self.accept_preview)
        reject_btn.clicked.connect(self.reject_preview)

        # Splitter for Code | Output (Native)
        self.splitter = QSplitter(Qt.Vertical)
        self.layout.addWidget(self.splitter)
        
        # 1. Web-based Editor
        self.web_view = QWebEngineView()
        self.web_view.setPage(LoggedPage(self.web_view)) # Use custom logged page
        self.bridge = WebEditorBridge(initial_code)
        self.bridge.selectionChanged.connect(self.on_selection_changed)
        self.bridge.previewAccepted.connect(self._on_js_preview_accepted)
        
        self.last_selection_text = ""
        self.last_selection_lines = ""
        
        self.channel = QWebChannel()
        self.channel.registerObject("pyBridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)
        
        # Store pending code and initial code
        self._initial_code = initial_code
        self._pending_code = None
        
        # Connect load finished signal
        self.web_view.loadFinished.connect(self.on_web_view_loaded)
        
        # Load the HTML template
        template_path = os.path.join(os.path.dirname(__file__), "..", "resources", "editor_template.html")
        template_path = os.path.abspath(template_path)
        
        # Set baseUrl so it can find local JS files
        base_url = QUrl.fromLocalFile(os.path.dirname(template_path) + "/")
        with open(template_path, "r", encoding="utf-8") as f:
            html_content = f.read()
            
        self.web_view.setHtml(html_content, baseUrl=base_url)
        self.splitter.addWidget(self.web_view)

        # Fix: Enable custom context menu for web_view
        self.web_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.web_view.customContextMenuRequested.connect(self.show_context_menu)

        # Tab widget for Output and Terminal
        from PySide6.QtWidgets import QTabWidget, QToolButton
        self.tab_widget = QTabWidget()
        # Styles applied in update_theme_styles()
        
        # Add clear button to tab widget corner
        self.clear_btn = QToolButton(self)
        self.clear_btn.setText("Clear")
        # Styles applied in update_theme_styles()
        self.clear_btn.clicked.connect(self.clear_current_tab)
        self.tab_widget.setCornerWidget(self.clear_btn, Qt.TopRightCorner)
        
        # Native Output Area
        self.output = QPlainTextEdit()
        self.output.setFont(QFont("Consolas", 10))
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Output terminal...")
        # Styles applied in update_theme_styles()
        self.tab_widget.addTab(self.output, "输出")
        
        # Terminal
        self.terminal = QPlainTextEdit()
        self.terminal.setFont(QFont("Consolas", 10))
        self.terminal.setReadOnly(False)
        # Styles applied in update_theme_styles()
        self.terminal.installEventFilter(self)
        self.command_history = []
        self.history_index = -1
        self.current_command = ""
        # Set initial terminal content with prompt
        self.terminal.setPlainText("Terminal: Type commands here (press Enter to execute)\n>>")
        self.tab_widget.addTab(self.terminal, "终端")

        # 3. Variable Explorer
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
        self.var_table = QTableWidget(0, 3)
        self.var_table.setHorizontalHeaderLabels(["名称", "类型", "值/预览"])
        self.var_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.var_table.verticalHeader().setVisible(False)
        self.var_table.setAlternatingRowColors(True)
        # Styles applied in update_theme_styles()
        self.var_table.itemDoubleClicked.connect(self.on_variable_opened)
        self.tab_widget.addTab(self.var_table, "变量")
        
        self.splitter.addWidget(self.tab_widget)
        
        # Set initial proportions
        self.splitter.setStretchFactor(0, 3) # Editor takes more space
        self.splitter.setStretchFactor(1, 1) # Output/Terminal area
        # Ensure splitter is resizeable with VSCode-like style
        self.splitter.setHandleWidth(1)  # Thin handle like VSCode
        self.splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: transparent;
                border: none;
            }
            QSplitter::handle:hover {
                background-color: #0078d4;
            }
        """)
        
        # Finally, apply all theme-aware styles now that all widgets are created
        self.update_theme()

    def _get_scrollbar_style(self):
        return """
            /* All scrollbars in this widget */
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 10px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #d0d0d0;
                min-height: 20px;
                border-radius: 5px;
                border: 2px solid transparent;
                background-clip: content-box;
            }
            QScrollBar::handle:vertical:hover {
                background: #a0a0a0;
            }
            /* Completely hide arrows by setting height to 0 and position */
            QScrollBar::add-line:vertical {
                height: 0px;
                subcontrol-position: bottom;
                subcontrol-origin: margin;
            }
            QScrollBar::sub-line:vertical {
                height: 0px;
                subcontrol-position: top;
                subcontrol-origin: margin;
            }
            QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {
                width: 0px;
                height: 0px;
                image: none;
            }

            QScrollBar:horizontal {
                border: none;
                background: transparent;
                height: 10px;
                margin: 0px;
            }
            QScrollBar::handle:horizontal {
                background: #d0d0d0;
                min-width: 20px;
                border-radius: 5px;
                border: 2px solid transparent;
                background-clip: content-box;
            }
            QScrollBar::handle:horizontal:hover {
                background: #a0a0a0;
            }
            /* Completely hide arrows */
            QScrollBar::add-line:horizontal {
                width: 0px;
                subcontrol-position: right;
                subcontrol-origin: margin;
            }
            QScrollBar::sub-line:horizontal {
                width: 0px;
                subcontrol-position: left;
                subcontrol-origin: margin;
            }
            QScrollBar::left-arrow:horizontal, QScrollBar::right-arrow:horizontal {
                width: 0px;
                height: 0px;
                image: none;
            }
            
            QScrollBar::add-page, QScrollBar::sub-page {
                background: none;
            }
            QAbstractScrollArea::corner, QMdiArea::corner {
                background: transparent;
                border: none;
            }
        """
        

    def get_code(self):
        return self.bridge._content

    def is_preview_active(self):
        return self._preview_original_code is not None or self.preview_bar.isVisible()

    def has_unsaved_changes(self):
        current_code = self.get_code()
        if self.script_path and os.path.exists(self.script_path):
            try:
                disk_code = open(self.script_path, "r", encoding="utf-8").read()
            except Exception:
                return True
            return current_code != disk_code
        return bool(current_code.strip())

    def get_script_state(self):
        current_code = self.get_code()
        base_code = self._preview_original_code
        if base_code is None and self.script_path and os.path.exists(self.script_path):
            try:
                base_code = open(self.script_path, "r", encoding="utf-8").read()
            except Exception:
                base_code = ""
        elif base_code is None:
            base_code = ""

        current_hash = hashlib.sha1(current_code.encode("utf-8")).hexdigest()
        base_hash = hashlib.sha1(base_code.encode("utf-8")).hexdigest()
        return {
            "editor_id": self.editor_id,
            "script_path": self.script_path,
            "is_preview_active": self.is_preview_active(),
            "has_unsaved_changes": self.has_unsaved_changes(),
            "preview_source": self._preview_source if self.is_preview_active() else "none",
            "base_hash": base_hash,
            "working_hash": current_hash,
            "should_run_from": "editor",
            "should_save_to": self.script_path,
        }

    def _on_js_preview_accepted(self):
        """Triggered from JS when preview is successfully accepted by user or API."""
        self._preview_original_code = None
        self._preview_source = "none"
        self.preview_bar.hide()
        # Optionally auto-save after accepting preview if file exists
        if hasattr(self, 'script_path') and self.script_path:
            # Add a small delay so textChanged signal properly finishes
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, lambda: self.save_code(self.script_path))

    def accept_preview(self):
        """Accept preview manually via UI."""
        self._preview_original_code = None
        self._preview_source = "none"
        if self.web_view.page():
            self.web_view.page().runJavaScript("window.acceptPreview()")
        self.preview_bar.hide()
        
    def reject_preview(self):
        """Reject preview manually via UI."""
        self._preview_original_code = None
        self._preview_source = "none"
        if self.web_view.page():
            self.web_view.page().runJavaScript("window.rejectPreview()")
        self.preview_bar.hide()

    def set_preview_code(self, new_code):
        """Compute diff and send preview command to Ace editor"""
        current_code = self.get_code()
        # Maintain the original baseline state across multiple preview edits
        if getattr(self, '_preview_original_code', None) is None:
            self._preview_original_code = current_code
        self._preview_source = "ai_preview"
            
        import difflib
        sm = difflib.SequenceMatcher(None, self._preview_original_code.splitlines(), new_code.splitlines())
        
        diff_blocks = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            # In a unified-style single-pane view where we set the NEW code, 
            # we should only highlight what's NEWly present (j1:j2).
            # 'remove' (i1:i2) means code that is GONE, so highlighting it on the NEW code 
            # at indices j1:j2 (which are the same for replacements) causes muddy overlap.
            if tag in ('replace', 'insert'):
                diff_blocks.append({"type": "add", "start_line": j1, "end_line": j2 - 1})
            elif tag == 'delete':
                # For deletions, we mark the 'insertion point' where code used to be
                # We'll use a special type 'delete-point' for JS to handle specially (e.g. underline)
                # j1 and j2 are the same for deletions. We mark the line ABOVE j1.
                diff_blocks.append({"type": "delete-point", "line": j1})
                
        # Handle empty case
        if not new_code and current_code:
            diff_blocks = [{"type": "add", "start_line": 0, "end_line": 0}] # Mark something or handle empty
                
        # Send to JS wrapper
        js_cmd = f"window.showPreview({json.dumps(new_code)}, {json.dumps(diff_blocks)})"
        if self.web_view.page():
            self.web_view.page().runJavaScript(js_cmd)
        
        self.preview_bar.show()

    def on_web_view_loaded(self, ok):
        """Handle web view load finished"""
        if ok:
            self._is_ready = True
            # Apply initial theme if queued
            if self._current_theme:
                # Direct call to ensure it's first
                self.web_view.page().runJavaScript(f"if(window.setTheme) window.setTheme('{self._current_theme}');")
            
            # Flush other pending scripts
            for js in self._pending_scripts:
                self.web_view.page().runJavaScript(js)
            self._pending_scripts = []
            
            # Add a small delay to ensure JavaScript is fully executed before setting code
            self._pending_code_timer.start(100)

    def _run_js(self, js_code):
        """Run JavaScript or queue it if not ready."""
        if self._is_ready and self.web_view.page():
            self.web_view.page().runJavaScript(js_code)
        else:
            self._pending_scripts.append(js_code)

    def set_pending_code(self):
        """Set pending code after JavaScript is fully loaded"""
        # Check if editor is initialized
        if self.web_view.page():
            def check_editor_initialized(result):
                if result:
                    # Set initial code if any
                    if self._initial_code:
                        self.set_code_directly(self._initial_code)
                        self.bridge._content = self._initial_code
                        self._initial_code = ""
                    # Set pending code if any (e.g., from script double-click)
                    elif self._pending_code:
                        self.set_code_directly(self._pending_code)
                        self.bridge._content = self._pending_code
                        self._pending_code = None
                else:
                    # Editor not initialized yet, try again after delay
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(100, self.set_pending_code)
            
            # Try to check if isEditorInitialized exists
            def check_function_exists(result):
                if result:
                    # Function exists, check if editor is initialized
                    self.web_view.page().runJavaScript("window.isEditorInitialized()", check_editor_initialized)
                else:
                    # Function doesn't exist yet, try again after delay
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(100, self.set_pending_code)
            
            self.web_view.page().runJavaScript("typeof window.isEditorInitialized === 'function'", check_function_exists)

    def set_code_directly(self, code):
        """Set code directly when web view is ready"""
        self.bridge._content = code
        if self.web_view.page():
            # Use silent=true to prevent feedback loop to Python bridge
            self.web_view.page().runJavaScript(f"window.setContent({json.dumps(code)}, true)")

    def set_code(self, code):
        self.bridge._content = code
        # Always store as pending code to ensure JavaScript is fully initialized
        self._pending_code = code
        
        # If web view is already loaded or being loaded, try to set it
        # We use a timer to ensure we don't block the main thread and allow Ace to initialize
        if hasattr(self, 'web_view') and self.web_view.page():
            self._pending_code_timer.start(50)

    def format_code(self):
        """Format the current code using autopep8."""
        code = self.get_code()
        if not code or not code.strip():
            return
            
        try:
            import autopep8
            # Use autopep8 to fix the code
            formatted_code = autopep8.fix_code(code, options={'aggressive': 1})
            
            if formatted_code != code:
                self.set_code(formatted_code)
                self.output.setPlainText("Python code formatted using autopep8.")
            else:
                self.output.setPlainText("Code is already PEP 8 compliant.")
        except ImportError:
            # Fallback to simple JS formatting if autopep8 is missing
            self.output.setPlainText("Warning: autopep8 not found. Using basic formatting.")
            self.web_view.page().runJavaScript("window.formatCode()")
        except Exception as e:
            self.output.setPlainText(f"Formatting error: {str(e)}")

    def comment_code(self):
        """Toggle comment for selected lines or current line."""
        if self.web_view.page():
            # Standard Ace toggle command is most reliable
            self.web_view.page().runJavaScript("editor.toggleCommentLines();")

    def _init_execution_context(self):
        """Initialize the persistent execution context."""
        import numpy as np
        from scripts.data.db_manager import DBManager as DBClass
        
        main_win = self.window()
        # Ensure we find the real main window if nested
        for widget in QApplication.topLevelWidgets():
            if hasattr(widget, 'mdi_area'): # MainWindow detection
                main_win = widget
                break

        self.execution_context = {
            "__name__": "__main__",
            "__file__": self.script_path or os.path.join(os.getcwd(), "untitled.py"),
            "db_path": self.db_path,
            "db": self.db,
            "app": main_win,
            "np": np,
            "DBManager": DBClass,
            "wells": main_win.get_all_well_info() if hasattr(main_win, 'get_all_well_info') else [],
        }

    def run_code(self):
        import io
        import contextlib
        
        code = self.get_code()
        
        # Capture stdout
        f = io.StringIO()
        
        # Switch to output tab before running
        self.tab_widget.setCurrentIndex(0)  # 0 is the index of "输出" tab
        self.output.setPlainText("Running...")
        
        # Inject print redirector and current file path into context
        self.execution_context["print"] = lambda *args: print(*args, file=f)
        self.execution_context["__file__"] = self.script_path or os.path.join(os.getcwd(), "untitled.py")
        self.execution_context["db_path"] = self.db_path
        
        try:
            with contextlib.redirect_stdout(f):
                exec(code, self.execution_context)
            result = f.getvalue()
            self.output.setPlainText(result if result else "Done (No Output)")
            # Update variables after successful execution
            self.update_variables_table(self.execution_context)
        except Exception as e:
            self.output.setPlainText(f"Error:\n{e}")

    def update_variables_table(self, context):
        """Update the variables table from the execution context."""
        import numpy as np
        
        # Filter variables: ignore private, modules, and functions
        display_vars = []
        for name, value in context.items():
            if name.startswith('_') or hasattr(value, '__module__') and value.__class__.__name__ == 'module':
                continue
            if name in ['app', 'db', 'DBManager', 'wells', 'np', 'print']:
                continue
            if callable(value):
                continue
            
            # Get type name
            type_name = type(value).__name__
            
            # Get value preview
            if isinstance(value, np.ndarray):
                preview = f"Array {value.shape} {value.dtype}"
            elif isinstance(value, (list, dict, set)):
                preview = f"{type_name} (len={len(value)})"
            else:
                preview = str(value)
                if len(preview) > 50:
                    preview = preview[:47] + "..."
            
            display_vars.append((name, type_name, preview))
        
        # Update Table UI
        self.var_table.setRowCount(len(display_vars))
        for row, (name, vtype, preview) in enumerate(display_vars):
            from PySide6.QtWidgets import QTableWidgetItem
            self.var_table.setItem(row, 0, QTableWidgetItem(name))
            self.var_table.setItem(row, 1, QTableWidgetItem(vtype))
            self.var_table.setItem(row, 2, QTableWidgetItem(preview))

        
    def on_variable_opened(self, item):
        """Handle variable double-click to show details."""
        row = item.row()
        var_name = self.var_table.item(row, 0).text()
        
        if var_name in self.execution_context:
            val = self.execution_context[var_name]
            diag = VariableInspectorDialog(var_name, val, self)
            diag.exec()

    def save_code(self, filename=None):
        """Save the current code. If self.script_path exists, overwrite it. Otherwise prompt for name."""
        code = self.get_code()
        if not code.strip():
            return False

        if filename:
            path = filename
            if not os.path.isabs(path):
                path = os.path.abspath(path)
            return self._perform_save(path, code)
             
        # Case 1: Overwrite existing file
        if self.script_path and os.path.exists(self.script_path):
            return self._perform_save(self.script_path, code)
            
        # Case 2: New file, prompt for name in scripts_user
        scripts_dir = "scripts_user"
        if not os.path.exists(scripts_dir):
            os.makedirs(scripts_dir)
            
        # 获取默认文件名：从窗口标题中提取
        default_name = ""
        main_window = self.window()
        if main_window:
            # 尝试获取子窗口标题
            for sub in main_window.mdi_area.subWindowList():
                if sub.widget() == self:
                    title = sub.windowTitle()
                    # 移除 "Script: " 前缀，提取文件名
                    if title.startswith("Script: "):
                        default_name = title.replace("Script: ", "")
                    elif title.startswith("Script "):
                        default_name = title.replace(" ", "_")
                    else:
                        default_name = title
                    if not default_name.endswith(".py"):
                        default_name += ".py"
                    break
        
        if not default_name:
            import time
            default_name = f"script_{int(time.time())}.py"
        
        # 弹出输入对话框 (Legacy behavior for quick saving to scripts_user)
        filename, ok = QInputDialog.getText(
            self,
            "Save Script",
            "Enter filename (will be saved to scripts_user):",
            text=default_name
        )
        
        if not ok or not filename.strip():
            return False
        
        filename = filename.strip()
        if not filename.endswith(".py"):
            filename += ".py"
            
        path = os.path.join(scripts_dir, filename)
        return self._perform_save(path, code)

    def save_as(self):
        """Save As with a file dialog."""
        code = self.get_code()
        if not code.strip():
            return False
            
        initial_dir = os.path.dirname(self.script_path) if self.script_path else os.getcwd()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Script As",
            initial_dir,
            "Python Files (*.py);;All Files (*)"
        )
        
        if file_path:
            return self._perform_save(file_path, code)
        return False

    def _perform_save(self, path, code):
        """Internal helper to write code to disk."""
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
            self.script_path = path
            self.output.setPlainText(f"Saved to {path}")
            
            # If we saved while in preview mode, the disk now matches the preview
            self._preview_original_code = None
            self._preview_source = "none"
            self.preview_bar.hide()
            if self.web_view.page():
                self.web_view.page().runJavaScript("if(window.clearPreviewMarkers) window.clearPreviewMarkers(); window._isPreviewActive = false;")
            
            # Update window title
            main_window = self.window()
            if main_window and hasattr(main_window, 'mdi_area'):
                for sub in main_window.mdi_area.subWindowList():
                    if sub.widget() == self:
                        sub.setWindowTitle(f"Script: {os.path.basename(path)}")
                        break
            
            self.script_saved.emit(path)
            return path
        except Exception as e:
            self.output.setPlainText(f"Save Error:\n{e}")
            return False
    

    
    def eventFilter(self, obj, event):
        """Handle keyboard events for terminal"""
        from PySide6.QtCore import QEvent
        if obj == self.terminal and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
                # Get current text and execute command
                text = self.terminal.toPlainText()
                # Extract the command (after the last prompt or from the last line)
                lines = text.split('\n')
                if lines:
                    # Find the last line that is not empty
                    for i in range(len(lines)-1, -1, -1):
                        if lines[i].strip():
                            # Check if it starts with prompt
                            if lines[i].startswith('>>'):
                                command = lines[i][2:].strip()
                            else:
                                # Treat the entire line as command
                                command = lines[i].strip()
                            if command:
                                self.execute_terminal_command(command)
                            break
                return True
            elif event.key() == Qt.Key_Up:
                # Navigate command history up
                if self.command_history and self.history_index < len(self.command_history) - 1:
                    self.history_index += 1
                    self.update_terminal_with_history()
                return True
            elif event.key() == Qt.Key_Down:
                # Navigate command history down
                if self.command_history and self.history_index > 0:
                    self.history_index -= 1
                    self.update_terminal_with_history()
                elif self.history_index == 0:
                    self.history_index = -1
                    self.update_terminal_with_history()
                return True
        return super().eventFilter(obj, event)
    
    def execute_terminal_command(self, command):
        """Execute terminal command"""
        # Add command to history
        if command and (not self.command_history or self.command_history[0] != command):
            self.command_history.insert(0, command)
            if len(self.command_history) > 50:  # Limit history size
                self.command_history = self.command_history[:50]
        self.history_index = -1
        
        # Execute command
        try:
            import io
            import contextlib
            
            # Inject print redirector into context (if not already there or to ensure fresh buffer)
            # Actually, for terminal we might want to capture and print immediately or just use shared
            
            # Capture stdout
            f = io.StringIO()
            with contextlib.redirect_stdout(f):
                exec(command, self.execution_context)
            result = f.getvalue()
            
            # Update variables after terminal execution
            self.update_variables_table(self.execution_context)
            
            # Update terminal with result
            current_text = self.terminal.toPlainText()
            if result:
                current_text += "\n" + result
            current_text += "\n>>"
            self.terminal.setPlainText(current_text)
            # Move cursor to end
            from PySide6.QtGui import QTextCursor
            self.terminal.moveCursor(QTextCursor.End)
        except Exception as e:
            # Show error
            current_text = self.terminal.toPlainText()
            current_text += f"\nError: {e}\n>>"
            self.terminal.setPlainText(current_text)
            # Move cursor to end
            from PySide6.QtGui import QTextCursor
            self.terminal.moveCursor(QTextCursor.End)
    
    def update_terminal_with_history(self):
        """Update terminal with history command"""
        current_text = self.terminal.toPlainText()
        # Remove current command line
        lines = current_text.split('\n')
        if lines and lines[-1].startswith('>>'):
            lines = lines[:-1]
        current_text = '\n'.join(lines)
        
        # Add history command
        if self.history_index >= 0 and self.history_index < len(self.command_history):
            current_text += "\n>>" + self.command_history[self.history_index]
        else:
            current_text += "\n>>"
        
        self.terminal.setPlainText(current_text)
        # Move cursor to end
        from PySide6.QtGui import QTextCursor
        self.terminal.moveCursor(QTextCursor.End)

    def clear_output(self):
        """Clear the output area"""
        self.output.clear()
        self.output.setPlaceholderText("Output terminal...")

    def clear_terminal(self):
        """Clear the terminal area"""
        self.terminal.clear()
        self.terminal.setPlainText("Terminal: Type commands here (press Enter to execute)\n>>")

    def clear_variables(self):
        """Clear the variables table and reset the execution context."""
        self.var_table.setRowCount(0)
        self._init_execution_context()
        self.output.setPlainText("Workspace cleared. Variables reset.")

    def clear_current_tab(self):
        """Clear the currently active tab (Output or Terminal)"""
        current_index = self.tab_widget.currentIndex()
        if current_index == 0:
            # Output tab
            self.clear_output()
        elif current_index == 1:
            # Terminal tab
            self.clear_terminal()
        elif current_index == 2:
            # Variables tab
            self.clear_variables()

    def get_output_text(self):
        """Get the text content of the output area"""
        return self.output.toPlainText()

    def get_terminal_text(self):
        """Get the text content of the terminal area"""
        return self.terminal.toPlainText()

    def run_terminal_command(self, command):
        """Run a command in the terminal (for AI tool use)"""
        if not command or not command.strip():
            return False
        
        # Add command to terminal display
        current_text = self.terminal.toPlainText()
        if current_text.endswith('>>'):
            current_text = current_text[:-2]
        current_text += f"\n>>{command}"
        self.terminal.setPlainText(current_text)
        
        # Execute the command
        self.execute_terminal_command(command.strip())
        return True

    def on_selection_changed(self, text, x, y, lineStr=""):
        """Handle selection change from Ace Editor."""
        self.last_selection_text = text
        self.last_selection_lines = lineStr if lineStr else "Code"

    def contextMenuEvent(self, event):
        """Redirect standard context menu event."""
        self.show_context_menu(event.pos())

    def show_context_menu(self, pos):
        """Show the custom context menu with AI features."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction, QCursor
        
        # Determine global position
        # If called from customContextMenuRequested (signal), pos is relative to sender
        # If called from contextMenuEvent (event), pos is relative to this widget
        if self.sender() == self.web_view:
            global_pos = self.web_view.mapToGlobal(pos)
        else:
            global_pos = self.mapToGlobal(pos)
        
        # Create context menu
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                border: 1px solid #d0d0d0;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px 6px 30px;
                color: #333333;
            }
            QMenu::item:selected {
                background-color: #f0f6ff;
                color: #0078d7;
            }
            QMenu::separator {
                height: 1px;
                background: #e0e0e0;
                margin: 4px 8px;
            }
            QMenu::icon {
                padding-left: 10px;
            }
        """)
        
        # 1. AI Actions (Top)
        chat_action = QAction("AI 聊天 (Chat)", self)
        chat_action.setShortcut("Ctrl+L")
        chat_action.triggered.connect(lambda: self.trigger_ai_action("", use_context=True))
        menu.addAction(chat_action)
        
        menu.addSeparator()

        # 2. Standard Actions
        undo_action = QAction("撤销 (Undo)", self)
        undo_action.triggered.connect(lambda: self.web_view.page().runJavaScript("editor.undo()"))
        menu.addAction(undo_action)
        
        redo_action = QAction("重做 (Redo)", self)
        redo_action.triggered.connect(lambda: self.web_view.page().runJavaScript("editor.redo()"))
        menu.addAction(redo_action)
        
        menu.addSeparator()
        
        copy_action = QAction("复制 (Copy)", self)
        copy_action.triggered.connect(lambda: self.web_view.page().runJavaScript("document.execCommand('copy')"))
        menu.addAction(copy_action)
        
        paste_action = QAction("粘贴 (Paste)", self)
        paste_action.triggered.connect(lambda: self.web_view.page().runJavaScript("document.execCommand('paste')"))
        menu.addAction(paste_action)
        
        # 3. Formatting Actions
        menu.addSeparator()
        format_action = QAction("格式化代码 (autopep8)", self)
        format_action.triggered.connect(self.format_code)
        menu.addAction(format_action)
        
        menu.exec(global_pos)

    def trigger_ai_action(self, prompt_prefix, text_override=None, use_context=False):
        """Trigger AI assistant with selected code and a prompt."""
        if use_context:
            # New mode: Add as tag to input box
            ai_widget = self.find_ai_assistant_widget()
            if ai_widget and hasattr(ai_widget, 'set_code_context'):
                filename = os.path.basename(self.script_path) if self.script_path else ""
                if not filename:
                    # Try to get from window title
                    main_window = self.window()
                    if main_window:
                        for sub in main_window.mdi_area.subWindowList():
                            if sub.widget() == self:
                                title = sub.windowTitle()
                                if title.startswith("Script: "):
                                    filename = title.replace("Script: ", "")
                                break
                if not filename:
                    filename = "Unsaved Script"
                
                # If no selection, use the whole file (optional, but usually context implies selection)
                text = text_override or self.last_selection_text
                lines = self.last_selection_lines or "Code"
                
                if not text:
                    # Fallback to whole file if no selection
                    self.web_view.page().runJavaScript("window.getSelectedText()", lambda t: self._add_context_callback(t, filename))
                else:
                    self._add_context_callback(text, filename, lines)
            return

        if text_override:
            # Inline popup case
            self._process_ai_prompt(prompt_prefix, text_override)
        else:
            # Context menu case
            self.web_view.page().runJavaScript("window.getSelectedText()", self._on_selected_text_received(prompt_prefix))

    def _add_context_callback(self, text, filename, lines=None):
        if not text:
            text = self.get_code()
            lines = f"1-{len(text.splitlines())}"
        
        ai_widget = self.find_ai_assistant_widget()
        if ai_widget:
            # Bring to front
            try:
                main_window = self.window()
                from PySide6.QtWidgets import QDockWidget
                for dock in main_window.findChildren(QDockWidget):
                    if dock.widget() == ai_widget:
                        dock.show()
                        dock.raise_()
                        break
            except: pass
            
            ai_widget.set_code_context(filename, lines or "Code", text)

    def _on_selected_text_received(self, prompt_prefix):
        def callback(selected_text):
            if not selected_text or not selected_text.strip():
                # If no selection, use entire code
                selected_text = self.get_code()
                if not selected_text.strip():
                    return
            self._process_ai_prompt(prompt_prefix, selected_text)
        
        return callback

    def _process_ai_prompt(self, prompt_prefix, selected_text):
        """Send prompt with code to AI."""
        prompt = f"{prompt_prefix}\n\n代码如下：\n```python\n{selected_text}\n```"
        
        # Find AI Assistant Widget
        ai_widget = self.find_ai_assistant_widget()
        if ai_widget:
            # ... existing logic to focus and send ...
            try:
                main_window = self.window()
                from PySide6.QtWidgets import QDockWidget
                for dock in main_window.findChildren(QDockWidget):
                    if dock.widget() == ai_widget:
                        dock.show()
                        dock.raise_()
                        break
            except:
                pass
            
            if hasattr(ai_widget, 'send_message'):
                ai_widget.send_message(prompt)
            else:
                self.output.setPlainText("Found AI widget but couldn't find send_message method.")
        else:
            self.output.setPlainText("Error: AI Assistant plugin not found. Please ensure it is loaded.")

    def find_ai_assistant_widget(self):
        """Helper to find the AIAssistantWidget in the application."""
        from PySide6.QtWidgets import QApplication
        for widget in QApplication.topLevelWidgets():
            # AIAssistantWidget is inside main window
            for child in widget.findChildren(QWidget):
                if child.__class__.__name__ == 'AIAssistantWidget':
                    return child
        return None

    def set_theme(self, theme_name):
        """External entry point for theme switching."""
        theme_name = theme_name.lower() if theme_name else "light"
        self._current_theme = theme_name
        self.update_theme(theme_name)
        # Also notify Web View (queued)
        self._run_js(f"if(window.setTheme) window.setTheme('{theme_name}');")

    def update_theme(self, theme_name=None):
        """Regenerate and apply all QSS styles based on current theme."""
        from core.app_config import app_config
        if theme_name is None:
            theme_name = app_config.get_theme_name()
        
        theme_name = theme_name.lower()
        is_dark = (theme_name == 'dark')
        
        from scripts.ui.theme_manager import ThemeManager
        c = lambda t: app_config.get_theme_color(t)
        
        bg = c('bg_pure')
        text = c('text_main')
        border = c('border_std')
        tab_bg = c('bg_dim')
        tab_hover = c('bg_header')
        accent = c('accent')
        tab_text = c('text_dim')
        
        # 1. Update Scrollbars
        self.setStyleSheet(self._get_scrollbar_style(theme_name))
        
        # 2. Toolbar
        self.toolbar.setStyleSheet(f"""
            QToolBar {{ 
                background-color: {bg}; 
                border-bottom: 1px solid {border}; 
                padding: 4px;
                spacing: 8px;
            }}
            QToolButton {{ 
                color: {text}; 
                padding: 4px 12px; 
                border-radius: 4px;
                border: 1px solid transparent;
                font-weight: 500;
            }}
            QToolButton:hover {{ 
                background-color: {tab_hover}; 
                color: {accent};
                border: 1px solid {c('accent_light')};
            }}
        """)
        
        # 3. Tab Widget
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.setAutoFillBackground(True)
        self.tab_widget.setStyleSheet(f"""
            QTabWidget {{ border: none; background-color: {bg}; outline: none; }}
            QTabWidget::pane {{ border: none; background-color: {bg}; top: 0px; }}
            QTabBar {{ background-color: {bg}; color: {text}; border: none; qproperty-drawBase: 0; }}
            QTabBar::tab {{
                padding: 8px 16px;
                background-color: {bg};
                border: none;
                margin-right: 2px;
                color: {tab_text};
                font-size: 11px;
                font-weight: 500;
            }}
            QTabBar::tab:selected {{
                color: {accent};
                background-color: {bg};
                border-bottom: 2px solid {accent};
            }}
            QTabBar::tab:hover {{ background-color: {tab_hover}; }}
        """)
        
        # 4. Clear Button (Inside Tab Corner)
        # We set background explicitly to {bg} instead of transparent to cover white header area
        self.clear_btn.setStyleSheet(f"""
            QToolButton {{
                background-color: {bg};
                border: none;
                padding: 6px 12px;
                color: {tab_text};
                font-size: 11px;
            }}
            QToolButton:hover {{
                background-color: {tab_hover};
                color: {accent};
                border-radius: 4px;
            }}
        """)
        
        # 8. Splitter
        self.splitter.setStyleSheet(f"""
            QSplitter {{ background-color: {bg}; border: none; }}
            QSplitter::handle {{
                background-color: {bg};
                border: none;
            }}
            QSplitter::handle:hover {{
                background-color: {accent};
            }}
        """)
        
        # 9. Web View (Force no border & Inject dynamic variables)
        self.web_view.setStyleSheet(f"QWebEngineView {{ background-color: {bg}; border: none; }}")
        
        # Inject CSS Variables into the Ace Editor Template
        css_vars = ThemeManager.get_web_theme_css(theme_name)
        css_content = css_vars.replace("\n", "\\n").replace("'", "\\'")
        js_inject = f"""
            var styleTag = document.getElementById('dynamic-theme-vars');
            if (styleTag) {{
                styleTag.innerHTML = '{css_content}';
            }}
        """
        self._run_js(js_inject)
        
        # 5. Output & Terminal
        edit_style = f"""
            QPlainTextEdit {{
                background-color: {bg}; 
                color: {text}; 
                border: none;
                padding: 5px;
                selection-background-color: {c('accent_light')};
                selection-color: {text};
            }}
        """
        self.output.setStyleSheet(edit_style)
        self.terminal.setStyleSheet(edit_style)
        
        # 6. Preview Bar
        preview_bg = c('accent_light')
        preview_border = c('border_std')
        preview_text = c('text_main')
        
        self.preview_bar.setStyleSheet(f"""
            QFrame {{ background-color: {preview_bg}; border-bottom: 1px solid {preview_border}; }}
            QLabel {{ color: {preview_text}; font-weight: 500; }}
            QPushButton {{ padding: 4px 12px; font-weight: bold; border-radius: 4px; }}
            QPushButton#acceptBtn {{ background-color: #2e7d32; color: white; border: none; }}
            QPushButton#acceptBtn:hover {{ background-color: #1b5e20; }}
            QPushButton#rejectBtn {{ background-color: #c62828; color: white; border: none; }}
            QPushButton#rejectBtn:hover {{ background-color: #b71c1c; }}
        """)
        
        # Original label inside preview_bar needs to be accessible or we rely on QSS inheritance
        # The label was created locally in __init__, so we depend on QSS selector QLabel.
        
        # 7. Variable Table
        self.var_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {bg};
                alternate-background-color: {tab_hover};
                color: {text};
                border: none;
                gridline-color: {border};
            }}
            QTableWidget::item {{ padding: 4px; }}
            QHeaderView::section {{
                background-color: {tab_hover};
                padding: 4px;
                border: none;
                border-bottom: 1px solid {border};
                font-weight: bold;
                color: {tab_text};
            }}
        """ + self._get_scrollbar_style(theme_name))

    def _get_scrollbar_style(self, theme_name=None):
        from core.app_config import app_config
        if theme_name is None:
            theme_name = app_config.get_theme_name()
        
        c = lambda t: app_config.get_theme_color(t)
        is_dark = (theme_name == 'dark')
        handle_bg = c('scrollbar_handle')
        handle_hover = c('scrollbar_handle_hover')
        
        return f"""
            QScrollBar:vertical {{
                border: none;
                background: transparent;
                width: 10px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {handle_bg};
                min-height: 20px;
                border-radius: 5px;
                border: 2px solid transparent;
                background-clip: content-box;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {handle_hover};
            }}
            QScrollBar:horizontal {{
                border: none;
                background: transparent;
                height: 10px;
                margin: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background: {handle_bg};
                min-width: 20px;
                border-radius: 5px;
                border: 2px solid transparent;
                background-clip: content-box;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {handle_hover};
            }}
            QScrollBar::add-line, QScrollBar::sub-line {{ border: none; background: none; }}
        """

    def closeEvent(self, event):
        """Cleanup resources on close"""
        if hasattr(self, '_pending_code_timer'):
            self._pending_code_timer.stop()
        
        # Break potential circular references
        if hasattr(self, 'web_view'):
            self.web_view.setPage(None)
            self.web_view.deleteLater()
            
        super().closeEvent(event)
