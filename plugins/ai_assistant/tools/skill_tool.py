import os
import json
import sys

# 关键修复：使用与 registry.py 完全一致的导入逻辑，防止双重导入导致的类校验失败
try:
    from .base_tool import BaseTool
    from .registry import register_tool
except ImportError:
    try:
        from plugins.ai_assistant.tools.base_tool import BaseTool
        from plugins.ai_assistant.tools.registry import register_tool
    except ImportError:
        # 最后的兜底
        from .base_tool import BaseTool
        from .registry import register_tool

import os
import sys

# 动态注入插件根目录，确保内部模块导入的家园始终在 path 中
_plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _plugin_root not in sys.path:
    sys.path.insert(0, _plugin_root)

try:
    from ..common.paths import PathResolver
except ImportError:
    try:
        from plugins.ai_assistant.common.paths import PathResolver
    except ImportError:
        PathResolver = None

@register_tool
class ReadSkillTool(BaseTool):
    """Tool for the AI to read specialized geoscience skills from the project."""
    
    def __init__(self, main_window=None, tool_executor=None, ui_bridge=None):
        name = "read_skill"
        description = (
            "Read a specialized geoscience skill's documentation. "
            "Use this when you need expert knowledge on LAS/DLIS files, rock physics, "
            "petrophysical formulas (Sw, Vsh, Phi), seismic attributes, or lithology."
        )
        args_schema = {
            "name": {
                "type": "string",
                "description": "The path or name of the skill to read (e.g., 'lasio', 'workflows/well-log-evaluation'). Use read_skill with an empty name to see the full list of path-based IDs."
            }
        }
        super().__init__(name, description, args_schema)
        self.main_window = main_window
        
        # Use centralized PathResolver
        self.project_root = PathResolver.get_project_root()
        
        # 动态导入 SkillService
        try:
            from ..services.skill_service import SkillService
        except ImportError:
            try:
                from plugins.ai_assistant.services.skill_service import SkillService
            except ImportError:
                SkillService = None
        
        self.skill_service = SkillService(self.project_root) if SkillService else None

    def execute(self, name=None):
        """Execute the skill reading operation with status check and metadata."""
        if not self.skill_service:
            return json.dumps({"ok": False, "error": "SkillService not initialized."})

        # 1. Check for disabled status
        from PySide6.QtCore import QSettings
        settings = QSettings("PyLog", "AIAssistant")
        disabled_skills = settings.value("disabled_skills", [])
        if isinstance(disabled_skills, str):
            try: disabled_skills = json.loads(disabled_skills)
            except: disabled_skills = []
        if not isinstance(disabled_skills, list): disabled_skills = []
        
        # 2. List all skills with descriptions if no name is provided
        if not name:
            all_skills = self.skill_service.list_skills()
            available = []
            for s in all_skills:
                if s in disabled_skills: continue
                meta = self.skill_service.get_skill_metadata(s)
                aliases = self.skill_service.get_skill_aliases(s)
                available.append({
                    "id": s,
                    "title": meta.get('title', s),
                    "description": meta.get('description', ''),
                    "aliases": aliases
                })
            
            return json.dumps({
                "ok": True,
                "message": "List of enabled specialized geoscience experts. Consult one by providing its 'id'.",
                "experts": available
            })

        # 2. Resolve aliases (id path / basename / frontmatter name)
        resolved, candidates = self.skill_service.resolve_skill_name(name)
        if not resolved:
            available = self.skill_service.list_skills()
            payload = {
                "ok": False,
                "error": f"Skill '{name}' not found or ambiguous.",
                "available_skills": available
            }
            if candidates:
                payload["candidates"] = candidates
            return json.dumps(payload)

        # 3. Block disabled skills
        if resolved in disabled_skills:
            return json.dumps({
                "ok": False,
                "error": f"The skill '{resolved}' is currently disabled by the user in Settings. Ask the user if you need to use this capability."
            })

        content = self.skill_service.get_skill_content(resolved)
        file_list = self.skill_service.list_skill_files(resolved)
        
        if content or file_list:
            return json.dumps({
                "ok": True,
                "skill": resolved,
                "content": content if content else "Main documentation (SKILL.md) is empty or missing.",
                "files": file_list,
                "message": f"Documentation and {len(file_list)} files found for skill '{resolved}'."
            })
        else:
            available = self.skill_service.list_skills()
            return json.dumps({
                "ok": False,
                "error": f"Skill '{resolved}' is empty.",
                "available_skills": available
            })
