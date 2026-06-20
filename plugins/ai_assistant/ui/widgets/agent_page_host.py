import json
import os

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from core.app_config import app_config
from scripts.ui.base_dialog import ThemeDialog
from scripts.ui.theme_manager import ThemeManager


class AgentPageBridge(QObject):
    """Generic bridge for agent-owned HTML pages."""

    pageReady = Signal()
    actionTriggered = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)

    @Slot(str)
    def log(self, message):
        if message == "Agent page ready":
            self.pageReady.emit()

    @Slot(str, str)
    def postAction(self, action, payload_json="{}"):
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except Exception:
            payload = {"raw": payload_json}
        self.actionTriggered.emit(action, payload)


class _AgentPageHostMixin:
    """Shared HTML page hosting behavior for dialog and MDI surfaces."""

    pageReady = Signal()
    actionTriggered = Signal(str, object)

    def _init_agent_page_host(self, template_name, payload=None, bridge=None):
        self.template_name = template_name
        self.payload = payload or {}
        self.bridge = bridge or AgentPageBridge(self)
        self._is_ready = False
        self._pending_scripts = []
        self._current_theme = app_config.get_theme_name().lower()

        self.web_view = QWebEngineView(self)
        self.web_view.page().setBackgroundColor(app_config.get_theme_qcolor("bg_pure"))
        self.channel = QWebChannel(self)
        self.channel.registerObject("pageBridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)

        self.bridge.pageReady.connect(self._on_page_ready)
        self.bridge.actionTriggered.connect(self.actionTriggered.emit)

        self._load_template()

    def _load_template(self):
        template_path = os.path.join(os.path.dirname(__file__), "..", "resources", self.template_name)
        template_path = os.path.abspath(template_path)
        with open(template_path, "r", encoding="utf-8") as handle:
            html = handle.read()
        base_url = QUrl.fromLocalFile(os.path.dirname(template_path) + "/")
        self.web_view.setHtml(html, baseUrl=base_url)

    def _on_page_ready(self):
        self._is_ready = True
        self.pageReady.emit()
        self._apply_theme(self._current_theme)
        self.set_payload(self.payload)
        self._flush_pending_scripts()

    def _flush_pending_scripts(self):
        if not self._is_ready:
            return
        while self._pending_scripts:
            script = self._pending_scripts.pop(0)
            self.web_view.page().runJavaScript(script)

    def execute_js(self, script):
        if self._is_ready:
            self.web_view.page().runJavaScript(script)
        else:
            self._pending_scripts.append(script)

    def set_payload(self, payload):
        self.payload = payload or {}
        encoded = json.dumps(self.payload, ensure_ascii=False)
        self.execute_js(f"if(window.setPagePayload) window.setPagePayload({encoded});")

    def update_theme(self, theme_name=None):
        theme = (theme_name or app_config.get_theme_name() or "light").lower()
        self._current_theme = theme
        self.web_view.page().setBackgroundColor(app_config.get_theme_qcolor("bg_pure"))
        self.web_view.setStyleSheet(f"QWebEngineView {{ background-color: {app_config.get_theme_color('bg_pure')}; border: none; }}")
        self._apply_theme(theme)

    def _apply_theme(self, theme_name):
        css_vars = ThemeManager.get_web_theme_css(theme_name)
        css_content = css_vars.replace("\n", "\\n").replace("'", "\\'")
        self.execute_js(f"if(window.setTheme) window.setTheme('{theme_name}');")
        self.execute_js(
            "var styleTag = document.getElementById('dynamic-theme-vars');"
            f"if (styleTag) {{ styleTag.innerHTML = '{css_content}'; }}"
        )


class AgentPageDialog(ThemeDialog, _AgentPageHostMixin):
    """Reusable host for local HTML pages that need Python callbacks."""

    pageReady = Signal()
    actionTriggered = Signal(str, object)

    def __init__(
        self,
        title,
        template_name,
        payload=None,
        bridge=None,
        size=(980, 720),
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(*size)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)

        self._init_agent_page_host(template_name, payload=payload, bridge=bridge)
        layout.addWidget(self.web_view)
        self.update_theme()


class AgentPageWidget(QWidget, _AgentPageHostMixin):
    """Reusable agent-owned page that can live inside the MDI workspace."""

    pageReady = Signal()
    actionTriggered = Signal(str, object)

    def __init__(self, title, template_name, payload=None, bridge=None, parent=None):
        super().__init__(parent)
        self.page_title = title
        self.page_subwindow = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._init_agent_page_host(template_name, payload=payload, bridge=bridge)
        layout.addWidget(self.web_view)
        self.update_theme()


def _resolve_main_window(parent):
    widget = parent
    while widget is not None:
        if hasattr(widget, "mdi_area"):
            return widget
        if hasattr(widget, "parentWidget") and widget.parentWidget():
            widget = widget.parentWidget()
        else:
            widget = widget.parent()

    for widget in QApplication.topLevelWidgets():
        if hasattr(widget, "mdi_area"):
            return widget
    return None


def _find_existing_mdi_page(main_window, page_id):
    mdi_area = getattr(main_window, "mdi_area", None)
    if not mdi_area:
        return None, None
    for sub in mdi_area.subWindowList():
        widget = sub.widget()
        if getattr(widget, "page_id", None) == page_id:
            return widget, sub
    return None, None


def find_agent_page(page_id, parent=None):
    main_window = _resolve_main_window(parent)
    if not main_window:
        return None, None
    return _find_existing_mdi_page(main_window, page_id)


def close_agent_page(page_id, parent=None):
    widget, sub = find_agent_page(page_id, parent=parent)
    if sub:
        sub.close()
        return True
    return False


def open_agent_page(
    page_id,
    title,
    template,
    payload=None,
    mode="dialog",
    size=(980, 720),
    bridge=None,
    parent=None,
):
    """Create a reusable local HTML page host."""
    if mode == "dialog":
        dialog = AgentPageDialog(
            title=title,
            template_name=template,
            payload=payload,
            bridge=bridge,
            size=size,
            parent=parent,
        )
        dialog.page_id = page_id
        dialog.page_mode = "dialog"
        return dialog

    if mode == "mdi":
        main_window = _resolve_main_window(parent)
        if not main_window or not hasattr(main_window, "mdi_area"):
            raise ValueError("MDI mode requires a main window with mdi_area")

        existing_widget, existing_sub = _find_existing_mdi_page(main_window, page_id)
        if existing_widget and existing_sub:
            existing_widget.set_payload(payload)
            existing_sub.setWindowTitle(title)
            main_window.mdi_area.setActiveSubWindow(existing_sub)
            existing_sub.show()
            return existing_widget

        widget = AgentPageWidget(
            title=title,
            template_name=template,
            payload=payload,
            bridge=bridge,
            parent=main_window,
        )
        widget.page_id = page_id
        widget.page_mode = "mdi"
        sub = main_window.mdi_area.addSubWindow(widget)
        sub.setWindowTitle(title)
        sub.resize(*size)
        sub.show()
        main_window.mdi_area.setActiveSubWindow(sub)
        widget.page_subwindow = sub
        return widget

    raise ValueError(f"Unsupported page mode: {mode}")
