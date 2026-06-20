import os

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMenu, QVBoxLayout, QWidget

from core.app_config import app_config
from scripts.ui.theme_manager import ThemeManager


def is_html_previewable(path):
    return bool(path) and str(path).lower().endswith((".html", ".htm"))


class HtmlPreviewWidget(QWidget):
    """Simple local HTML preview surface for workspace documents."""
    openSourceRequested = Signal(str)

    def __init__(self, file_path=None, parent=None):
        super().__init__(parent)
        self.file_path = None
        self._current_theme = (app_config.get_theme_name() or "Light").lower()
        self._template_loaded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.web_view = QWebEngineView(self)
        self.web_view.setContextMenuPolicy(Qt.CustomContextMenu)
        layout.addWidget(self.web_view)
        self.web_view.customContextMenuRequested.connect(self._show_context_menu)
        self.web_view.loadFinished.connect(self._on_load_finished)

        self._load_shell_template()
        self.update_theme()
        if file_path:
            self.load_file(file_path)

    def update_theme(self):
        self._current_theme = (app_config.get_theme_name() or "Light").lower()
        bg = app_config.get_theme_color("bg_pure")
        self.web_view.page().setBackgroundColor(app_config.get_theme_qcolor("bg_pure"))
        self.web_view.setStyleSheet(f"QWebEngineView {{ background-color: {bg}; border: none; }}")
        self._apply_page_theme()

    def load_file(self, file_path):
        abs_path = os.path.abspath(file_path)
        self.file_path = abs_path
        self._update_preview_payload()

    def refresh_page(self):
        self._run_js("""
            (function() {
                var iframe = document.getElementById('previewFrame');
                if (!iframe || !iframe.src) return;
                iframe.src = iframe.src;
            })();
        """)

    def open_in_system_browser(self):
        if self.file_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.file_path))

    def _show_context_menu(self, position):
        menu = QMenu(self)

        refresh_action = QAction("刷新", self)
        refresh_action.triggered.connect(self.refresh_page)
        menu.addAction(refresh_action)

        open_source_action = QAction("在编辑器打开源码", self)
        open_source_action.triggered.connect(lambda: self.openSourceRequested.emit(self.file_path or ""))
        menu.addAction(open_source_action)

        open_browser_action = QAction("在系统浏览器打开", self)
        open_browser_action.triggered.connect(self.open_in_system_browser)
        menu.addAction(open_browser_action)

        menu.exec(self.web_view.mapToGlobal(position))

    def _on_load_finished(self, _ok):
        self._template_loaded = True
        self._apply_page_theme()
        self._update_preview_payload()

    def _load_shell_template(self):
        template_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "plugins",
            "ai_assistant",
            "ui",
            "resources",
            "html_preview_template.html",
        )
        template_path = os.path.abspath(template_path)
        with open(template_path, "r", encoding="utf-8") as handle:
            html = handle.read()
        base_url = QUrl.fromLocalFile(os.path.dirname(template_path) + "/")
        self.web_view.setHtml(html, base_url)

    def _apply_page_theme(self):
        css_vars = ThemeManager.get_web_theme_css(self._current_theme)
        scrollbar_css = self._build_scrollbar_css()
        combined_css = f"{css_vars}\n{scrollbar_css}"
        escaped_css = combined_css.replace("\\", "\\\\").replace("`", "\\`")
        escaped_theme = self._current_theme.replace("\\", "\\\\").replace("'", "\\'")
        script = f"""
            (function() {{
                try {{
                    document.documentElement.classList.remove('dark-mode', 'light-mode', 'sakura-mode', 'manga-mode');
                    document.documentElement.classList.add('{escaped_theme}-mode');
                    var styleTag = document.getElementById('pylog-preview-theme');
                    if (!styleTag) {{
                        styleTag = document.createElement('style');
                        styleTag.id = 'pylog-preview-theme';
                        document.head.appendChild(styleTag);
                    }}
                    styleTag.textContent = `{escaped_css}`;
                }} catch (error) {{
                    console.error('Failed to apply PyLog preview theme', error);
                }}
            }})();
        """
        self._run_js(script)

    def _update_preview_payload(self):
        if not self._template_loaded or not self.file_path:
            return
        src = QUrl.fromLocalFile(self.file_path).toString()
        payload = {
            "title": os.path.basename(self.file_path),
            "summary": "本地 HTML 预览，和 Agent 页面共用统一主题壳。",
            "path": self.file_path,
            "src": src,
            "injectedCss": f"{ThemeManager.get_web_theme_css(self._current_theme)}\n{self._build_scrollbar_css()}",
        }
        import json
        self._run_js(f"if(window.setPreviewPayload) window.setPreviewPayload({json.dumps(payload, ensure_ascii=False)});")

    def _run_js(self, script):
        self.web_view.page().runJavaScript(script)

    @staticmethod
    def _build_scrollbar_css():
        handle = app_config.get_theme_color("scrollbar_handle")
        handle_hover = app_config.get_theme_color("scrollbar_handle_hover")
        border = app_config.get_theme_color("border_std")
        return f"""
html, body {{
    scrollbar-width: thin;
    scrollbar-color: {handle} transparent;
}}

::-webkit-scrollbar {{
    width: 12px;
    height: 12px;
}}

::-webkit-scrollbar-track {{
    background: transparent;
}}

::-webkit-scrollbar-thumb {{
    background: {handle};
    border-radius: 999px;
    border: 2px solid transparent;
    background-clip: padding-box;
}}

::-webkit-scrollbar-thumb:hover {{
    background: {handle_hover};
    border-radius: 999px;
    border: 2px solid transparent;
    background-clip: padding-box;
}}

::-webkit-scrollbar-corner {{
    background: transparent;
}}

* {{
    scrollbar-width: thin;
    scrollbar-color: {handle} transparent;
}}

*:not(select)::-webkit-scrollbar-thumb {{
    background: {handle};
    border-radius: 999px;
    border: 2px solid transparent;
    background-clip: padding-box;
}}

*:not(select)::-webkit-scrollbar-thumb:hover {{
    background: {handle_hover};
}}
"""
