import os
import sys
import shutil
import re

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

class SkillService:
    """Service to discover and read AI Agent skills from the workspace."""

    def __init__(self, project_root=None):
        if not project_root:
            project_root = PathResolver.get_project_root()
            
        self.project_root = project_root
        self.skills_dir = PathResolver.get_skills_dir(project_root)

    def list_skills(self, disabled_list=None):
        """Recursively find all directories containing a SKILL.md file."""
        if not os.path.exists(self.skills_dir):
            return []
        
        all_skills = []
        for root, dirs, files in os.walk(self.skills_dir):
            if "SKILL.md" in files:
                # Calculate relative path from skills_dir as the ID
                rel_path = os.path.relpath(root, self.skills_dir)
                # Normalize to forward slashes (AI-friendly and cross-platform)
                skill_id = rel_path.replace("\\", "/")
                
                # Filter out hidden directories (starting with .)
                if any(part.startswith(".") for part in skill_id.split("/")):
                    continue
                
                # "." indicates the root directory (allowed if SKILL.md is there, but usually skills are in subdirs)
                if skill_id == ".": continue
                
                all_skills.append(skill_id)
        
        if disabled_list:
            return [s for s in all_skills if s not in disabled_list]
        return sorted(all_skills)

    @staticmethod
    def _normalize_skill_name(name):
        if not name:
            return ""
        normalized = str(name).strip().replace("\\", "/")
        if normalized.startswith("$"):
            normalized = normalized[1:]
        return normalized.strip("/")

    def _extract_frontmatter_name(self, skill_id):
        """Extract frontmatter `name` (if present) without full metadata parse."""
        skill_path = os.path.join(self.skills_dir, skill_id, "SKILL.md")
        if not os.path.exists(skill_path):
            return ""
        try:
            with open(skill_path, "r", encoding="utf-8") as f:
                content = f.read()
            if not content.startswith("---"):
                return ""
            parts = content.split("---", 2)
            if len(parts) < 3:
                return ""
            for line in parts[1].splitlines():
                stripped = line.strip()
                if stripped.lower().startswith("name:"):
                    return stripped.split(":", 1)[1].strip().strip("'\"")
        except Exception:
            return ""
        return ""

    def get_skill_aliases(self, skill_id):
        aliases = []
        base = skill_id.split("/")[-1]
        if base:
            aliases.append(base)
        frontmatter_name = self._extract_frontmatter_name(skill_id)
        if frontmatter_name and frontmatter_name not in aliases:
            aliases.append(frontmatter_name)
        return aliases

    def resolve_skill_name(self, skill_name, disabled_list=None):
        """
        Resolve user-provided skill reference to canonical id.
        Supports id path, basename alias, and frontmatter `name`.
        Returns: (resolved_id|None, candidate_ids[list])
        """
        normalized = self._normalize_skill_name(skill_name)
        if not normalized:
            return None, []

        skills = self.list_skills(disabled_list=disabled_list)
        if not skills:
            return None, []

        direct = [s for s in skills if s.lower() == normalized.lower()]
        if direct:
            return direct[0], direct

        base_matches = [s for s in skills if s.split("/")[-1].lower() == normalized.lower()]
        if len(base_matches) == 1:
            return base_matches[0], base_matches
        if len(base_matches) > 1:
            return None, sorted(base_matches)

        fm_matches = []
        for s in skills:
            fm_name = self._extract_frontmatter_name(s)
            if fm_name and fm_name.lower() == normalized.lower():
                fm_matches.append(s)
        if len(fm_matches) == 1:
            return fm_matches[0], fm_matches
        if len(fm_matches) > 1:
            return None, sorted(fm_matches)

        fuzzy = [s for s in skills if normalized.lower() in s.lower()]
        if len(fuzzy) == 1:
            return fuzzy[0], fuzzy
        return None, sorted(fuzzy)

    @staticmethod
    def _quote_yaml_scalar(value):
        text = str(value or "")
        text = text.replace("\\", "\\\\").replace('"', '\\"')
        return f"\"{text}\""

    def delete_skill(self, skill_name):
        """Physically delete the skill directory from disk."""
        skill_name = self._normalize_skill_name(skill_name)
        if not skill_name:
            return False
        skill_path = os.path.abspath(os.path.join(self.skills_dir, skill_name))
        skills_root = os.path.abspath(self.skills_dir)
        if not skill_path.startswith(skills_root + os.sep):
            return False
        if os.path.exists(skill_path) and os.path.isdir(skill_path):
            try:
                shutil.rmtree(skill_path)
                return True
            except Exception as e:
                print(f"Error deleting skill {skill_name}: {e}")
                return False
        return False

    def create_skill(self, skill_name, title=None, description=""):
        """Create a new skill directory with starter SKILL.md."""
        skill_name = self._normalize_skill_name(skill_name)
        if not skill_name:
            return False, "Skill id cannot be empty."
        if skill_name == "." or ".." in skill_name.split("/"):
            return False, "Invalid skill id."
        if any(part.startswith(".") for part in skill_name.split("/")):
            return False, "Hidden path segments are not allowed."
        if not re.match(r"^[A-Za-z0-9._/\-]+$", skill_name):
            return False, "Skill id can only contain letters, numbers, '.', '_', '-', '/'."

        skill_dir = os.path.join(self.skills_dir, skill_name)
        skill_file = os.path.join(skill_dir, "SKILL.md")
        if os.path.exists(skill_file):
            return False, "Skill already exists."

        os.makedirs(skill_dir, exist_ok=True)
        final_title = title or skill_name.split("/")[-1]
        yaml_header = "---\n"
        yaml_header += f"name: {self._quote_yaml_scalar(final_title)}\n"
        yaml_header += f"description: {self._quote_yaml_scalar(description)}\n"
        yaml_header += "---\n\n"
        body = (
            f"# {final_title}\n\n"
            "Describe when to use this skill, expected workflow, and key cautions.\n"
        )
        try:
            with open(skill_file, "w", encoding="utf-8") as f:
                f.write(yaml_header + body)
            return True, skill_name
        except Exception as e:
            return False, str(e)

    def get_skill_content(self, skill_name, include_frontmatter=False):
        """Read specific skill content, optionally stripping YAML frontmatter."""
        skill_path = os.path.join(self.skills_dir, skill_name, "SKILL.md")
        if os.path.exists(skill_path):
            try:
                with open(skill_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                if not include_frontmatter and content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        return parts[2].strip()
                return content
            except: return ""
        return ""

    def get_skill_metadata(self, skill_name):
        """Extract metadata (title, description) from SKILL.md with robust YAML and MD support."""
        content = self.get_skill_content(skill_name, include_frontmatter=True)
        if not content:
            return {"title": skill_name, "description": "Expertise data missing."}
            
        metadata = {"title": skill_name, "description": ""}
        
        # 1. Robust YAML Frontmatter Parsing
        if content.startswith("---"):
            try:
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    header = parts[1]
                    body = parts[2]
                    
                    lines = header.split("\n")
                    desc_lines = []
                    capturing_desc = False
                    
                    for line in lines:
                        stripped = line.strip()
                        if not stripped: continue
                        
                        if stripped.startswith("description:"):
                            capturing_desc = True
                            val = line.split(":", 1)[1].strip()
                            if val and val not in ["|", ">"]:
                                desc_lines.append(val)
                        elif capturing_desc:
                            # If the line is indented, it's part of the multiline description
                            if line.startswith("  ") or line.startswith("\t"):
                                desc_lines.append(stripped)
                            elif ":" in stripped:
                                # New key started, stop capturing
                                capturing_desc = False
                            else:
                                desc_lines.append(stripped)
                        elif stripped.startswith("name:"):
                            metadata["title"] = line.split(":", 1)[1].strip()
                    
                    if desc_lines:
                        metadata["description"] = " ".join(desc_lines).strip()
                        return metadata
            except: pass
        else:
            body = content

        # 2. Advanced Fallback: Scan Markdown Body
        try:
            # Remove assets/links for cleaner description
            lines = body.split("\n")
            for line in lines:
                clean = line.strip()
                # Skip headers, images, separator lines, and lists
                if not clean or clean.startswith("#") or clean.startswith("!") or clean.startswith("---") or clean.startswith("-"):
                    continue
                # Pick the first substantial paragraph
                if len(clean) > 20: 
                    metadata["description"] = clean[:250] + ("..." if len(clean) > 250 else "")
                    break
        except: pass
        
        if not metadata["description"]:
            metadata["description"] = "Specialized AI expertise for well logging and geoscience."
            
        return metadata

    def update_skill_content(self, skill_name, title, description, markdown_body):
        """Write back metadata and body to SKILL.md."""
        file_path = os.path.join(self.skills_dir, skill_name, "SKILL.md")
        if not os.path.exists(os.path.dirname(file_path)):
            return False
            
        yaml_header = "---\n"
        yaml_header += f"name: {self._quote_yaml_scalar(title)}\n"
        if "\n" in str(description or ""):
            yaml_header += "description: |\n"
            for line in str(description).splitlines():
                yaml_header += f"  {line}\n"
        else:
            yaml_header += f"description: {self._quote_yaml_scalar(description)}\n"
        yaml_header += "---\n\n"
        
        full_content = yaml_header + markdown_body.strip()
        
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(full_content)
            return True
        except Exception as e:
            print(f"Error updating skill {skill_name}: {e}")
            return False

    def list_skill_files(self, skill_name):
        """Recursively list all files in the skill directory, excluding hidden/caches."""
        skill_path = os.path.join(self.skills_dir, skill_name)
        if not os.path.exists(skill_path) or not os.path.isdir(skill_path):
            return []
            
        file_list = []
        for root, dirs, files in os.walk(skill_path):
            # Prune hidden dirs and __pycache__
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for f in files:
                if f.startswith("."): continue
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, skill_path).replace("\\", "/")
                file_list.append(rel_path)
        return sorted(file_list)

    def get_all_skills_summary(self, disabled_list=None):
        """Get a summary of all available (and enabled) skills with descriptions."""
        skills = self.list_skills(disabled_list=disabled_list)
        if not skills:
            return "No specialized geoscience skills currently enabled."
        
        summary = "Available specialized geoscience skills (Consult via `read_skill`):\n"
        for s in skills:
            meta = self.get_skill_metadata(s)
            title = meta.get('title', s)
            desc = meta.get('description', 'No description.')
            aliases = [a for a in self.get_skill_aliases(s) if a.lower() != s.lower()]
            if aliases:
                alias_text = ", aliases: " + ", ".join([f"`{a}`" for a in aliases])
            else:
                alias_text = ""
            summary += f"- `{s}` ({title}{alias_text}): {desc}\n"
        return summary

    def get_skill_summaries(self, disabled_list=None):
        """Return structured metadata for enabled skills."""
        summaries = []
        for skill_id in self.list_skills(disabled_list=disabled_list):
            meta = self.get_skill_metadata(skill_id)
            aliases = [alias for alias in self.get_skill_aliases(skill_id) if alias.lower() != skill_id.lower()]
            summaries.append({
                "id": skill_id,
                "title": meta.get("title") or skill_id,
                "description": meta.get("description") or "",
                "aliases": aliases,
            })
        return summaries
