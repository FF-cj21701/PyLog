from .api_docs import APIDocumentation
import os
import sys
import json
from PySide6.QtCore import QSettings


class SystemPrompts:
    """Central repository for all system prompts used in the application."""

    @staticmethod
    def _get_tools_description():
        """Return tool descriptions discovered from the local tool registry."""
        try:
            current_file = os.path.abspath(__file__)
            ai_assistant_dir = os.path.dirname(os.path.dirname(current_file))
            plugins_dir = os.path.dirname(ai_assistant_dir)
            project_root = os.path.dirname(plugins_dir)

            if project_root not in sys.path:
                sys.path.insert(0, project_root)

            from ..tools.registry import tool_registry

            tools_dir = os.path.join(ai_assistant_dir, "tools")
            tool_registry.discover(tools_dir)

            tools_desc = []
            for tool_class in tool_registry.tools:
                try:
                    tool_instance = tool_class()
                    spec = tool_instance.spec
                    tools_desc.append(f"- `{spec.name}`: {spec.to_model_description()}")
                except Exception:
                    fallback_name = tool_class.__name__.replace("Tool", "").lower()
                    tools_desc.append(f"- `{fallback_name}`: {tool_class.__doc__ or 'No description'}")

            return "\n".join(tools_desc) if tools_desc else "- No tools available"
        except Exception:
            return "- Error retrieving tools description"

    @staticmethod
    def _get_skills_info():
        """Return a summary of enabled AI skills."""
        try:
            current_file = os.path.abspath(__file__)
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_file))))

            try:
                from ..services.skill_service import SkillService
            except ImportError:
                if project_root not in sys.path:
                    sys.path.insert(0, project_root)
                from plugins.ai_assistant.services.skill_service import SkillService

            settings = QSettings("PyLog", "AIAssistant")
            disabled_skills = settings.value("disabled_skills", [])
            if isinstance(disabled_skills, str):
                try:
                    disabled_skills = json.loads(disabled_skills)
                except Exception:
                    disabled_skills = []

            skill_service = SkillService(project_root)
            return skill_service.get_all_skills_summary(disabled_list=disabled_skills)
        except Exception as e:
            return f"- Error retrieving skills: {str(e)}"

    @staticmethod
    def _get_whitelist_info():
        """Return the configured file-access whitelist for tool usage."""
        try:
            whitelist = os.environ.get("PYLOG_TOOL_WHITELIST", "")
            if whitelist:
                dirs = whitelist.split(";")
                return "\n".join([f"- {d}" for d in dirs if d])
            return "- No whitelist configured"
        except Exception:
            return "- Unable to retrieve whitelist"

    @staticmethod
    def _get_workspace_scope_info():
        """Return AI workspace scope guidance for verification behavior."""
        try:
            try:
                from ..common.paths import PathResolver
            except ImportError:
                from plugins.ai_assistant.common.paths import PathResolver

            scope = PathResolver.get_ai_workspace_scope()
            if scope == "scripts_user":
                return (
                    "- Current AI workspace scope: scripts_user\n"
                    "- Use script-level verification for scripts_user files. Do not run project-level pytest unless the user explicitly requests it."
                )
            return "- Current AI workspace scope: project"
        except Exception:
            return "- Current AI workspace scope: project"

    SCRIPTING_GUIDELINES = (
        "## PYLOG SCRIPTING\n"
        "- For non-trivial PyLog scripts, consult `read_skill(name='pylog-scripting')` before coding.\n"
        "- Use `pylog_api` imports only; never invent `pylog` or `pylog.core` APIs.\n"
        "- For large curves, avoid forcing full arrays unless needed; prefer lazy/data-access APIs.\n"
        "- New AI-generated scripts should use the `ai_` filename prefix.\n\n"
    )

    IDENTITY_GUIDELINES = (
        "## IDENTITY\n"
        "- You are AI Assistant for ALIVE/PyLog well-log data analysis, visualization, and scripting.\n"
        "- For greetings, introduce yourself briefly as AI Assistant.\n\n"
    )

    OPERATIONAL_GUIDELINES = (
        "## OPERATING RULES\n"
        "- Prefer the shortest reliable path; avoid duplicate tool calls and unnecessary detours.\n"
        "- Gather facts with tools before asserting file, data, or runtime state.\n"
        "- Read before write: inspect the target file/state before modifying it.\n"
        "- For open preview/draft scripts, treat the preview as the same script; use `get_script_state`, then save/run by editor id when available.\n"
        "- For non-trivial tasks, call `finish` to terminate the loop. Use a short or empty `final_answer` if visible content already answered the user.\n"
        "- After modifying files or data, verify at the narrowest correct scope before finishing.\n\n"
    )

    TOOL_DISCOVERY_GUIDELINES = (
        "## TOOL DISCOVERY\n"
        "- Initially callable: finish, get_help, search_tools, load_tools, and task-plan tools.\n"
        "- Tools listed in [Active Tools] are callable now; do not load them again.\n"
        "- If a needed capability is missing, call `search_tools`, then `load_tools` for the most relevant 3-5 tools.\n"
        "- If `search_tools` says `can_call_now=true`, call that tool directly.\n"
        "- `get_help` gives docs only; it does not activate tools.\n\n"
    )

    SCRIPT_EXECUTION_GUIDELINES = (
        "## SCRIPT EXECUTION\n"
        "- If background script execution succeeds, do not rerun it just to inspect output; read returned logs if needed.\n"
        "- Verify preview scripts with preview-aware save/run tools instead of creating duplicate files.\n"
        "- Background scripts must not directly manipulate Qt/app widgets; use PyLog tools or whitelisted `ui_actions`.\n\n"
    )

    PLANNING_GUIDELINES = (
        "## PLANNING\n"
        "- Use `create_task_plan` only for tasks that truly need 3+ execution steps.\n"
        "- Keep plans short: 3-5 sequential steps with concise titles.\n"
        "- Use `update_task_plan` only for meaningful progress changes; if work is done, call `finish`.\n\n"
    )

    CODE_EXPLORATION_PLAYBOOK = (
        "## CODE EXPLORATION\n"
        "- Prefer symbol/reference tools for code structure; use text search as fallback.\n"
        "- Read the target content before patching.\n"
        "- Verify scripts with script-level tools; verify shared source with project-aware tools.\n\n"
    )

    GEOSCIENCE_SKILL_GUIDELINES = (
        "## SKILLS\n"
        "- Enabled skills appear in [Skills Summary]. Use `read_skill(name='skill_name')` before detailed petrophysics or PyLog scripting workflows.\n\n"
    )

    @classmethod
    def get_default_chat_prompt(cls):
        """Build the default chat system prompt."""
        whitelist_info = cls._get_whitelist_info()
        workspace_scope_info = cls._get_workspace_scope_info()

        return (
            "You are AI Assistant in ALIVE/PyLog.\n\n"
            + cls.IDENTITY_GUIDELINES
            + cls.OPERATIONAL_GUIDELINES
            + cls.TOOL_DISCOVERY_GUIDELINES
            + cls.SCRIPT_EXECUTION_GUIDELINES
            + cls.PLANNING_GUIDELINES
            + cls.CODE_EXPLORATION_PLAYBOOK
            + "## FILE ACCESS PERMISSIONS\n"
            + "File tools can only access files within:\n"
            + f"{whitelist_info}\n\n"
            + "## AI WORKSPACE SCOPE\n"
            + f"{workspace_scope_info}\n\n"
            + cls.GEOSCIENCE_SKILL_GUIDELINES
            + cls.SCRIPTING_GUIDELINES
            + "## CORE API SUMMARY (Search for more via `get_help`)\n"
            + APIDocumentation.CORE_API_SUMMARY
        )

    DEFAULT_CHAT = None

    @classmethod
    def clear_cache(cls):
        """Reset the cached system prompt to force regeneration."""
        cls.DEFAULT_CHAT = None

    @classmethod
    def get_prompt(cls):
        """Get the system prompt, generating it if not cached."""
        if cls.DEFAULT_CHAT is None:
            cls.DEFAULT_CHAT = cls.get_default_chat_prompt()
        return cls.DEFAULT_CHAT

    def __init__(self):
        """Pre-initialize the default chat prompt if needed."""
        SystemPrompts.get_prompt()
