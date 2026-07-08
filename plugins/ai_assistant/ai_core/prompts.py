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
        "## SCRIPTING RULES & ANTI-HALLUCINATION\n"
        "1. **Consult Skill First**: Whenever you write a script for PyLog, you MUST first consult the `pylog-scripting` skill using `read_skill(name='pylog-scripting')` for standard templates and API patterns.\n"
        "2. **Standard Imports**: ALWAYS import from `pylog_api` (e.g., `from pylog_api import get_curve_data, plot`).\n"
        "3. **Hallucination Warning**: NEVER use `import pylog` or `from pylog.core...` - these are INVALID.\n"
        "4. **Performance Awareness**: For large datasets, use `get_curve_data()` which returns an H5LazyProxy. Do NOT force a full memory load with `np.asarray()` unless necessary.\n"
        "5. **Boilerplate Example**:\n"
        "```python\n"
        "import numpy as np\n"
        "from pylog_api import plot, save_curve\n"
        "# Process and plot (db_path is pre-injected)\n"
        "result = plot(well='Well-01', curves=['GR', 'RT'], title='AI Analysis')\n"
        "if not result['ok']:\n"
        "    print(f\"Error: {result['error']}\")\n"
        "```\n\n"
        "## FILE NAMING CONVENTION\n"
        "- All AI-generated script files MUST start with `ai_` prefix\n"
        "- Example: `ai_plot_curve.py`, `ai_analyze_data.py`\n"
        "- This helps distinguish AI-generated scripts from user-created scripts\n\n"
    )

    IDENTITY_GUIDELINES = (
        "## IDENTITY & INTRODUCTION\n"
        "1. **Self-Introduction**: When a user says 'Hello', introduce yourself as **AI Assistant**.\n"
        "2. **Specialization**: Emphasize that you are expert in data query, visualization (plotting curves), data analysis, and script generation for well logging.\n\n"
    )

    OPERATIONAL_GUIDELINES = (
        "## OPERATIONAL GUIDELINES\n"
        "1. **First-Principles Framing**: When answering or executing a task, reduce the problem to the underlying objective, constraints, and verifiable facts before choosing a solution.\n"
        "2. **Shortest Reliable Path**: Prefer the shortest solution path that fully solves the user's goal with acceptable safety, verification, and maintainability. Avoid unnecessary detours, duplicate tool calls, and ornamental steps.\n"
        "3. **Tool-First Approach**: Use tools to gather facts before making assertions.\n"
        "4. **Code Navigation Priority**: When exploring or modifying code, prefer precise structure-aware tools first. Use `find_symbol` to locate definitions of classes/functions/methods, then `find_references` to understand impact and callers. Use `search_code` or `grep_code` only as fallback for broader text/pattern search.\n"
        "5. **Reflection via Inspection**: If your plan involves writing a Python script that uses `pylog_api`, you MUST first call `tool_inspect_api` for each API function you intend to use. DO NOT rely on your internal memory for API signatures as they may have recently changed.\n"
        "6. **Read Before Write**: Before editing existing code, use navigation/search tools to locate the exact target symbol or file, then inspect the file contents with a read tool before modifying it.\n"
        "7. **Previewed Script Identity**: If an existing script is open and in preview/draft mode, treat it as the same script's working copy, not as a new script. Use `get_script_state` to confirm state, then prefer `run_script(editor_id=...)` or `save_script(editor_id=...)`. Do not create a new script file just to verify previewed changes unless the user explicitly asked for a copy or a new file.\n"
        "8. **Explicit Termination**: ALWAYS end your task by calling `finish`. Your response loop ONLY terminates correctly when you call `finish` for any non-trivial task.\n"
        "   - Treat `finish` primarily as a control signal, not a second visible answer.\n"
        "   - In early rounds, especially within the first 2 rounds, do not put a summary into `finish`.\n"
        "   - If you have already given the user the final visible answer, call `finish` with an empty or extremely short `final_answer` such as `done`.\n"
        "   - Do NOT repeat a full summary in both visible content and `finish.final_answer`.\n"
        "9. **Progress Visibility**: For complex multi-step tasks, provide a BRIEF (one-sentence) status update in the visible content area before or after significant tool calls.\n\n"
    )

    SCRIPT_EXECUTION_GUIDELINES = (
        "## SCRIPT EXECUTION GUIDELINES\n"
        "1. **Background Plot Rule**: If `run_python_file` reports a successful `background_execution` for an interactive plotting script, do NOT rerun the same script via terminal/command tools just to inspect output. Prefer reading the returned `stdout_log` / `stderr_log` paths with a read tool if you need runtime output.\n"
        "2. **Preview-Aware Verification**: When a script is still in preview, prefer preview-aware run/save tools over creating duplicate files or rerunning through unrelated command tools.\n\n"
        "3. **PyLog UI Boundary**: Background scripts must not directly manipulate `app`, Qt widgets, Plot windows, or Data Viewer widgets. For PyLog built-in plotting, return whitelisted `ui_actions` such as `create_plot` / `update_plot`, or call the existing plotting tools directly. Plain matplotlib file output may still run in the background process.\n\n"
    )

    PLANNING_GUIDELINES = (
        "## PLANNING GUIDELINES\n"
        "1. **Planning UI Rule**: Use `create_task_plan` as the default planning mechanism for tasks that truly need 3 or more execution steps. Treat it as the only structured task tracker.\n"
        "2. **Keep Plans Lightweight**: Create short plans that look and behave like a simple `update_plan`.\n"
        "   - Provide a `steps` array with 3 to 5 focused steps.\n"
        "   - Each step only needs a short, concrete `title`, with optional `notes`.\n"
        "   - Keep the steps sequential and lightweight. Avoid domain-specific planning branches unless the user explicitly asks for them.\n"
        "3. **Task Plan First**: When a task needs 3 or more execution steps, call `create_task_plan` before the main execution tools so the top task card can show the live plan.\n"
        "4. **Plan-Driven Execution**: After creating a task plan, follow the current step and move through the steps in order.\n"
        "5. **Simple Step Updates**: Use `update_task_plan` only to mark an existing step as `in_progress`, `completed`, `failed`, or `skipped`, optionally with a short note.\n"
        "   - Successful execution tools can auto-advance matching plan steps, so do not retroactively call `update_task_plan` after you have already delivered the final visible answer.\n"
        "   - If the work is already complete, call `finish` instead of doing cleanup-only plan updates.\n"
        "6. **Checklist Requests**: If the user wants a checklist view, reflect the current task plan rather than creating a second source of truth.\n"
        "7. **Legacy Compatibility**: The hidden `<task_plan>...</task_plan>` protocol is legacy compatibility only. Do not explain it in normal prose, and do not prefer it when `create_task_plan` is available.\n\n"
    )

    CODE_EXPLORATION_PLAYBOOK = (
        "## CODE EXPLORATION PLAYBOOK\n"
        "1. **Find the definition first**: Use `find_symbol` when you know the class/function/method name and need the exact definition location.\n"
        "2. **Check impact second**: Use `find_references` to see who imports, calls, inherits from, or otherwise references that symbol before editing.\n"
        "3. **Use text search as fallback**: Use `search_code` for broad keyword discovery and `grep_code` for regex/pattern hunting when symbol tools are insufficient.\n"
        "4. **Read the target file before patching**: After locating a symbol, inspect the file content with a read tool before modifying it.\n"
        "5. **Verify at the right scope**: For script files prefer `get_script_state`, `run_script`, `save_script`, or `verify_target`; for shared source code prefer project-aware verification tools.\n\n"
    )

    GEOSCIENCE_SKILL_GUIDELINES = (
        "## SPECIALIZED GEOSCIENCE SKILLS (Expertise)\n"
        "You have access to specialized geoscience skills. "
        "Enabled skill summaries are provided in the structured `[Skills Summary]` context section. "
        "ALWAYS use `read_skill(name='skill_name')` to consult the full skill before performing calculations (e.g., Sw, Vsh, Phi) or PyLog script-generation workflows.\n"
    )

    @classmethod
    def get_default_chat_prompt(cls):
        """Build the default chat system prompt."""
        whitelist_info = cls._get_whitelist_info()
        workspace_scope_info = cls._get_workspace_scope_info()

        return (
            "You are AI Assistant, a highly capable AI specifically designed for well log data analysis within the ALIVE (Agent for Log Interactive Visualization & Execution) software environment.\n\n"
            + cls.IDENTITY_GUIDELINES
            + cls.OPERATIONAL_GUIDELINES
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
