import asyncio
import json
import os
import threading

from PySide6.QtCore import QSettings, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from core.app_config import app_config

from ..ai_core.api_client import AsyncAIWorker
from ..ai_core.config import AIConfig
from ..ai_core.mcp_integration import parse_mcp_args_input, test_mcp_server_connection
from ..ai_core.prompts import SystemPrompts
from ..services.skill_service import SkillService
from .widgets.agent_page_host import AgentPageBridge, close_agent_page, open_agent_page


SETTINGS_PAGE_ID = "ai_settings"


def get_project_root():
    """Find the PyLog project root from this plugin module."""
    curr = os.path.abspath(__file__)
    for _ in range(10):
        curr = os.path.dirname(curr)
        if os.path.exists(os.path.join(curr, ".agents")):
            return curr
        if os.path.exists(os.path.join(curr, "main.py")):
            return curr
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


TOOL_CATEGORY_RULES = [
    ("Plot / Window", {"plotting", "plot_spec", "plot_style", "curve_style", "track_style", "image_style", "colormap"}),
    ("Data / Wells", {"geoscience", "pylog", "well", "curve", "data"}),
    ("Scripts", {"script", "python", "run script", "script editor"}),
    ("Files / Workspace", {"file", "patch", "workspace", "document", "html"}),
    ("Search / Discovery", {"search", "find", "inspect", "help", "locate"}),
    ("Planning", {"task plan", "plan"}),
    ("Verification", {"verify", "test", "pytest", "lint", "format", "import"}),
    ("Skills", {"skill"}),
]


def _tool_text_blob(spec):
    parts = [
        getattr(spec, "name", ""),
        getattr(spec, "description", ""),
        getattr(spec, "usage_hint", ""),
        " ".join(getattr(spec, "capability_tags", []) or []),
        " ".join(getattr(spec, "domain_tags", []) or []),
        " ".join(getattr(spec, "keywords", []) or []),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def categorize_local_tool_spec(spec):
    """Return the settings-page category for a local tool spec."""
    text = _tool_text_blob(spec)
    for category, markers in TOOL_CATEGORY_RULES:
        if any(marker in text for marker in markers):
            return category
    return "General"


def build_local_tool_category_groups(specs):
    groups = {}
    for spec in specs or []:
        if getattr(spec, "source", "local") != "local":
            continue
        category = categorize_local_tool_spec(spec)
        groups.setdefault(category, []).append(spec)

    for category in groups:
        groups[category].sort(key=lambda item: getattr(item, "name", ""))

    category_order = {name: index for index, (_name, _markers) in enumerate(TOOL_CATEGORY_RULES) for name in [_name]}
    return dict(sorted(groups.items(), key=lambda item: (category_order.get(item[0], 999), item[0])))


def _json_response(ok=True, **payload):
    payload["ok"] = bool(ok)
    return json.dumps(payload, ensure_ascii=False)


def _run_async_blocking(coro):
    """Run an async operation from a synchronous QWebChannel slot."""
    result = {}

    def runner():
        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


class SettingsBridge(AgentPageBridge):
    settingsSaved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = AIConfig()
        self.settings = QSettings("PyLog", "AIAssistant")

    @Slot(result=str)
    def getSettingsPayload(self):
        try:
            return _json_response(True, payload=self._build_payload())
        except Exception as exc:
            return _json_response(False, error=str(exc))

    @Slot(str, result=str)
    def saveSettings(self, payload_json):
        try:
            payload = json.loads(payload_json or "{}")
            self._save_payload(payload)
            self.settingsSaved.emit()
            return _json_response(True, payload=self._build_payload(), message="Settings saved.")
        except Exception as exc:
            return _json_response(False, error=str(exc))

    @Slot(result=str)
    def refreshTools(self):
        try:
            return _json_response(True, tools=self._get_tools_payload())
        except Exception as exc:
            return _json_response(False, error=str(exc))

    @Slot(result=str)
    def chooseFolder(self):
        folder = QFileDialog.getExistingDirectory(None, "Select Folder")
        return _json_response(True, path=folder or "")

    @Slot(result=str)
    def chooseFile(self):
        file_path, _ = QFileDialog.getOpenFileName(None, "Select File", "", "All Files (*.*)")
        return _json_response(True, path=file_path or "")

    @Slot(str, result=str)
    def fetchModels(self, profile_json):
        try:
            profile = json.loads(profile_json or "{}")
            api_key = str(profile.get("api_key") or "").strip()
            base_url = str(profile.get("base_url") or "").strip()
            if not api_key or not base_url:
                return _json_response(False, error="API Key and Base URL are required.")
            models = _run_async_blocking(AsyncAIWorker.list_models(api_key, base_url))
            return _json_response(True, models=models or [])
        except Exception as exc:
            return _json_response(False, error=str(exc))

    @Slot(str, str, result=str)
    def testMcpServer(self, name, config_json):
        try:
            conf = json.loads(config_json or "{}")
            tool_names = _run_async_blocking(test_mcp_server_connection(name, conf))
            return _json_response(True, tools=tool_names or [])
        except Exception as exc:
            return _json_response(False, error=str(exc))

    @Slot(str, result=str)
    def parseMcpArgs(self, args_text):
        try:
            return _json_response(True, args=parse_mcp_args_input(args_text or ""))
        except Exception as exc:
            return _json_response(False, error=str(exc))

    @Slot(str, result=str)
    def createSkill(self, skill_id):
        try:
            service = SkillService(get_project_root())
            ok, message = service.create_skill(skill_id)
            if not ok:
                return _json_response(False, error=message)
            self._clear_prompt_cache()
            return _json_response(True, skills=self._get_skills_payload())
        except Exception as exc:
            return _json_response(False, error=str(exc))

    @Slot(str, result=str)
    def deleteSkill(self, skill_id):
        try:
            service = SkillService(get_project_root())
            if not service.delete_skill(skill_id):
                return _json_response(False, error=f"Failed to delete skill: {skill_id}")
            disabled = self._get_disabled_skills()
            if skill_id in disabled:
                disabled.remove(skill_id)
                self.settings.setValue("disabled_skills", json.dumps(disabled))
            self._clear_prompt_cache()
            return _json_response(True, skills=self._get_skills_payload())
        except Exception as exc:
            return _json_response(False, error=str(exc))

    @Slot(str, result=str)
    def updateSkill(self, payload_json):
        try:
            payload = json.loads(payload_json or "{}")
            service = SkillService(get_project_root())
            skill_id = str(payload.get("id") or "").strip()
            ok = service.update_skill_content(
                skill_id,
                payload.get("title") or skill_id,
                payload.get("description") or "",
                payload.get("instruction") or "",
            )
            if not ok:
                return _json_response(False, error=f"Failed to update skill: {skill_id}")
            self._clear_prompt_cache()
            return _json_response(True, skills=self._get_skills_payload())
        except Exception as exc:
            return _json_response(False, error=str(exc))

    @Slot()
    def closeSettingsPage(self):
        close_agent_page(SETTINGS_PAGE_ID, parent=self.parent())

    def _build_payload(self):
        return {
            "profiles": self.config.get_profiles(),
            "current_profile": self.config.get_current_profile_name(),
            "behavior": {
                "max_rounds": self.config.get_max_rounds(),
                "max_history": self.config.get_max_history(),
                "auto_load": app_config.get_ai_auto_load(),
                "mcp_enabled": self.config.get_mcp_enabled(),
            },
            "whitelist": self.config.get_whitelist(),
            "mcp_servers": self.config.get_mcp_servers(),
            "disabled_skills": self._get_disabled_skills(),
            "skills": self._get_skills_payload(),
            "tools": self._get_tools_payload(),
            "theme": app_config.get_theme_name(),
        }

    def _save_payload(self, payload):
        profiles = payload.get("profiles")
        if isinstance(profiles, list):
            safe_profiles = [p for p in profiles if isinstance(p, dict) and str(p.get("name") or "").strip()]
            if not safe_profiles:
                raise ValueError("At least one profile is required.")
            self.config.set_profiles(safe_profiles)

        current_profile = str(payload.get("current_profile") or "").strip()
        if current_profile:
            self.config.set_current_profile_name(current_profile)

        behavior = payload.get("behavior") if isinstance(payload.get("behavior"), dict) else {}
        if "max_rounds" in behavior:
            self.config.set_max_rounds(int(behavior.get("max_rounds") or 1))
        if "max_history" in behavior:
            self.config.set_max_history(int(behavior.get("max_history") or 1))
        if "auto_load" in behavior:
            app_config.set_ai_auto_load(bool(behavior.get("auto_load")))
        if "mcp_enabled" in behavior:
            self.config.set_mcp_enabled(bool(behavior.get("mcp_enabled")))

        whitelist = payload.get("whitelist")
        if isinstance(whitelist, list):
            self.config.set_whitelist([str(item) for item in whitelist if str(item).strip()])

        mcp_servers = payload.get("mcp_servers")
        if isinstance(mcp_servers, dict):
            self.config.set_mcp_servers(mcp_servers)

        disabled_skills = payload.get("disabled_skills")
        if isinstance(disabled_skills, list):
            self.settings.setValue("disabled_skills", json.dumps([str(item) for item in disabled_skills]))

        self._clear_prompt_cache()

    def _get_tools_payload(self):
        from ..tools.registry import tool_registry

        tools_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools"))
        tool_registry.discover(tools_dir)
        specs = [spec for spec in tool_registry.get_tool_specs() if getattr(spec, "source", "local") == "local"]
        groups = build_local_tool_category_groups(specs)

        categories = []
        for category, items in groups.items():
            categories.append({
                "name": category,
                "tools": [self._tool_spec_payload(spec) for spec in items],
            })
        return {
            "total": sum(len(category["tools"]) for category in categories),
            "categories": categories,
        }

    def _tool_spec_payload(self, spec):
        return {
            "name": spec.name,
            "description": spec.description,
            "tags": list(spec.capability_tags or spec.domain_tags or []),
            "risk": spec.risk_level,
            "keywords": list(getattr(spec, "keywords", []) or []),
            "usage_hint": getattr(spec, "usage_hint", "") or "",
        }

    def _get_skills_payload(self):
        service = SkillService(get_project_root())
        disabled = set(self._get_disabled_skills())
        skills = []
        for skill_id in service.list_skills():
            meta = service.get_skill_metadata(skill_id)
            skills.append({
                "id": skill_id,
                "title": meta.get("title") or skill_id,
                "description": meta.get("description") or "",
                "aliases": service.get_skill_aliases(skill_id),
                "enabled": skill_id not in disabled,
                "instruction": service.get_skill_content(skill_id, include_frontmatter=False),
            })
        return skills

    def _get_disabled_skills(self):
        raw = self.settings.value("disabled_skills", [])
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = []
        else:
            parsed = raw
        return parsed if isinstance(parsed, list) else []

    def _clear_prompt_cache(self):
        if SystemPrompts:
            SystemPrompts.clear_cache()


def open_ai_settings_page(parent=None, on_saved=None):
    bridge = SettingsBridge(parent)
    if on_saved:
        bridge.settingsSaved.connect(on_saved)
    return open_agent_page(
        page_id=SETTINGS_PAGE_ID,
        title="AI Settings",
        template="settings_template.html",
        payload={},
        mode="mdi",
        size=(1120, 760),
        bridge=bridge,
        parent=parent,
    )
