import os
import re
import ast
import fnmatch
import importlib
from pathlib import Path

try:
    from .base_tool import BaseTool
except ImportError:
    try:
        from plugins.ai_assistant.tools.base_tool import BaseTool
    except ImportError:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        BaseTool = importlib.import_module("base_tool").BaseTool

try:
    from .registry import register_tool
except ImportError:
    try:
        from plugins.ai_assistant.tools.registry import register_tool
    except ImportError:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        register_tool = importlib.import_module("registry").register_tool


CODE_EXTENSIONS = ('.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.go', '.rs', '.cpp', '.h', '.c')


def _project_root():
    return os.getcwd()


def _iter_code_files(directory=None, file_pattern=None):
    root = directory or _project_root()
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
        for file in files:
            if not file.endswith(CODE_EXTENSIONS):
                continue
            filepath = os.path.join(current_root, file)
            rel_path = os.path.relpath(filepath, root).replace("\\", "/")
            if file_pattern:
                normalized_pattern = file_pattern.replace("\\", "/")
                if not (
                    fnmatch.fnmatch(file, normalized_pattern)
                    or fnmatch.fnmatch(rel_path, normalized_pattern)
                    or fnmatch.fnmatch(filepath.replace("\\", "/"), normalized_pattern)
                ):
                    continue
            yield filepath, rel_path


def _read_lines(filepath):
    try:
        return Path(filepath).read_text(encoding='utf-8', errors='ignore').splitlines()
    except Exception:
        return []


def _get_context(lines, match_index, context_lines=2):
    start = max(0, match_index - context_lines)
    end = min(len(lines), match_index + context_lines + 1)
    return [line.rstrip() for line in lines[start:end]]


def _safe_parse_python(filepath):
    try:
        source = Path(filepath).read_text(encoding='utf-8', errors='ignore')
        return ast.parse(source), source.splitlines()
    except Exception:
        return None, []


def _node_end_lineno(node):
    return getattr(node, "end_lineno", None) or getattr(node, "lineno", None)


def _build_symbol_record(filepath, rel_path, node, symbol_name, symbol_type, parent_name=None):
    return {
        "name": symbol_name,
        "type": symbol_type,
        "file": filepath,
        "relative_path": rel_path,
        "line_number": getattr(node, "lineno", None),
        "end_line_number": _node_end_lineno(node),
        "parent": parent_name,
    }


class _PythonSymbolCollector(ast.NodeVisitor):
    def __init__(self):
        self.symbols = []
        self.scope_stack = []

    def visit_ClassDef(self, node):
        parent = self.scope_stack[-1] if self.scope_stack else None
        self.symbols.append((node, node.name, "class", parent))
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node):
        parent = self.scope_stack[-1] if self.scope_stack else None
        symbol_type = "method" if parent else "function"
        self.symbols.append((node, node.name, symbol_type, parent))
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_AsyncFunctionDef(self, node):
        parent = self.scope_stack[-1] if self.scope_stack else None
        symbol_type = "async_method" if parent else "async_function"
        self.symbols.append((node, node.name, symbol_type, parent))
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_Assign(self, node):
        parent = self.scope_stack[-1] if self.scope_stack else None
        if parent:
            return
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.symbols.append((node, target.id, "variable", parent))
        self.generic_visit(node)


def _collect_python_symbols(filepath, rel_path):
    tree, _lines = _safe_parse_python(filepath)
    if not tree:
        return []
    collector = _PythonSymbolCollector()
    collector.visit(tree)
    return [
        _build_symbol_record(filepath, rel_path, node, symbol_name, symbol_type, parent_name)
        for node, symbol_name, symbol_type, parent_name in collector.symbols
    ]


class _PythonReferenceCollector(ast.NodeVisitor):
    def __init__(self, symbol, filepath, rel_path, lines):
        self.symbol = symbol.strip()
        self.filepath = filepath
        self.rel_path = rel_path
        self.lines = lines
        self.matches = []
        self.parents = []

    def visit(self, node):
        self.parents.append(node)
        try:
            return super().visit(node)
        finally:
            self.parents.pop()

    def _parent(self):
        if len(self.parents) >= 2:
            return self.parents[-2]
        return None

    def _add_match(self, node, reference_type, symbol_name=None):
        if not getattr(node, "lineno", None):
            return
        line_index = node.lineno - 1
        self.matches.append({
            "file": self.filepath,
            "relative_path": self.rel_path,
            "line_number": node.lineno,
            "column": getattr(node, "col_offset", 0) + 1,
            "content": self.lines[line_index].rstrip() if 0 <= line_index < len(self.lines) else "",
            "context": _get_context(self.lines, line_index),
            "reference_type": reference_type,
            "matched_symbol": symbol_name or self.symbol,
        })

    def visit_Import(self, node):
        for alias in node.names:
            if alias.name == self.symbol or alias.asname == self.symbol:
                self._add_match(node, "import", alias.asname or alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        module_name = node.module or ""
        if module_name == self.symbol:
            self._add_match(node, "import_module", module_name)
        for alias in node.names:
            if alias.name == self.symbol or alias.asname == self.symbol:
                self._add_match(node, "import_from", alias.asname or alias.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        if node.name == self.symbol:
            self._add_match(node, "definition", node.name)
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == self.symbol:
                self._add_match(base, "inherit", base.id)
            elif isinstance(base, ast.Attribute) and base.attr == self.symbol:
                self._add_match(base, "inherit_attribute", base.attr)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        if node.name == self.symbol:
            self._add_match(node, "definition", node.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        if node.name == self.symbol:
            self._add_match(node, "definition", node.name)
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        if isinstance(func, ast.Name) and func.id == self.symbol:
            self._add_match(func, "call", func.id)
        elif isinstance(func, ast.Attribute) and func.attr == self.symbol:
            self._add_match(func, "attribute_call", func.attr)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        parent = self._parent()
        if node.attr == self.symbol:
            if isinstance(parent, ast.Call) and parent.func is node:
                reference_type = "attribute_call"
            elif isinstance(parent, ast.ClassDef):
                reference_type = "inherit_attribute"
            else:
                reference_type = "attribute_access"
            self._add_match(node, reference_type, node.attr)
        self.generic_visit(node)

    def visit_Name(self, node):
        if node.id != self.symbol:
            self.generic_visit(node)
            return

        parent = self._parent()
        if isinstance(parent, ast.Call) and parent.func is node:
            reference_type = "call"
        elif isinstance(parent, ast.ClassDef):
            reference_type = "inherit"
        elif isinstance(parent, ast.Assign):
            reference_type = "assignment"
        elif isinstance(parent, ast.AnnAssign):
            reference_type = "annotation"
        elif isinstance(parent, ast.keyword):
            reference_type = "keyword_argument"
        else:
            reference_type = "name"
        self._add_match(node, reference_type, node.id)
        self.generic_visit(node)


def _find_python_symbol_references(filepath, rel_path, symbol):
    tree, lines = _safe_parse_python(filepath)
    if not tree:
        return []

    collector = _PythonReferenceCollector(symbol, filepath, rel_path, lines)
    collector.visit(tree)
    matches = collector.matches

    unique = []
    seen = set()
    for item in matches:
        key = (item["line_number"], item["column"], item["reference_type"], item.get("matched_symbol"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _find_text_references(filepath, rel_path, symbol):
    lines = _read_lines(filepath)
    if not lines:
        return []

    regex = re.compile(rf"\b{re.escape(symbol)}\b")
    matches = []
    for index, line in enumerate(lines, 1):
        match = regex.search(line)
        if match:
            matches.append({
                "file": filepath,
                "relative_path": rel_path,
                "line_number": index,
                "column": match.start() + 1,
                "content": line.rstrip(),
                "context": _get_context(lines, index - 1),
                "reference_type": "text",
            })
    return matches


@register_tool
class SearchCodeTool(BaseTool):
    def __init__(self, main_window=None):
        super().__init__("search_code", "Search for code patterns, functions, or keywords across the codebase. Use this to understand project structure, find existing implementations, or locate specific code.", {
            "query": {
                "type": "string",
                "description": "Search query - can be a function name, class name, keyword, or code pattern"
            },
            "file_pattern": {
                "type": "string",
                "description": "Optional file pattern to filter search (e.g., '*.py', 'plugins/**/*.py'). Default searches all files.",
                "nullable": True
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return. Default is 20.",
                "nullable": True
            }
        }, metadata={
            "required_args": ["query"],
            "capability_tags": ["search", "navigation"],
            "domain_tags": ["code"],
            "keywords": [
                "search code",
                "find code",
                "find implementation",
                "find function",
                "find class",
                "find keyword",
                "search project",
                "codebase search",
            ],
            "usage_hint": "Use this when you know a symbol name, keyword, or behavior but do not yet know the file path.",
        })
        self.main_window = main_window

    def execute(self, query=None, file_pattern=None, max_results=None):
        if not query or not query.strip():
            return {"error": "query is required"}
        
        try:
            import sys
            
            results = []
            max_results = max_results or 20
            query = query.strip()
            
            for filepath, rel_path in _iter_code_files(file_pattern=file_pattern):
                if len(results) >= max_results:
                    break
                lines = _read_lines(filepath)
                if not lines:
                    continue
                matches = []
                for i, line in enumerate(lines, 1):
                    if query.lower() in line.lower():
                        matches.append({
                            "line_number": i,
                            "content": line.rstrip(),
                            "context": _get_context(lines, i - 1)
                        })
                if matches:
                    results.append({
                        "file": filepath,
                        "relative_path": rel_path,
                        "matches": matches[:5]
                    })
            
            return {
                "ok": True,
                "query": query,
                "total_files": len(results),
                "results": results
            }
        except Exception as e:
            return {"error": str(e)}


@register_tool
class FindFilesTool(BaseTool):
    def __init__(self, main_window=None):
        super().__init__("find_files", "Find files by name pattern using glob patterns. Use this to locate specific files or groups of files in the project.", {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match files (e.g., '*.py', 'plugins/**/*.py', 'scripts_user/*.py')"
            },
            "directory": {
                "type": "string",
                "description": "Directory to search in. Default is current working directory.",
                "nullable": True
            }
        }, metadata={
            "required_args": ["pattern"],
            "capability_tags": ["search", "path_discovery"],
            "domain_tags": ["code", "script"],
            "keywords": [
                "find file",
                "find files",
                "search files",
                "locate file",
                "locate path",
                "glob search",
                "filepath lookup",
            ],
            "usage_hint": "Use this first when another tool requires filepath but the exact path is unknown.",
        })
        self.main_window = main_window

    def execute(self, pattern=None, directory=None):
        if not pattern or not pattern.strip():
            return {"error": "pattern is required"}
        
        try:
            from glob import glob
            
            search_dir = directory or os.getcwd()
            search_pattern = os.path.join(search_dir, pattern.strip())
            
            files = glob(search_pattern, recursive=True)
            
            file_info = []
            for filepath in sorted(files):
                try:
                    stat = os.stat(filepath)
                    file_info.append({
                        "path": filepath,
                        "size": stat.st_size,
                        "modified": stat.st_mtime
                    })
                except Exception:
                    file_info.append({
                        "path": filepath,
                        "size": 0,
                        "modified": 0
                    })
            
            return {
                "ok": True,
                "pattern": pattern,
                "directory": search_dir,
                "total_files": len(file_info),
                "files": file_info
            }
        except Exception as e:
            return {"error": str(e)}


@register_tool
class GrepCodeTool(BaseTool):
    def __init__(self, main_window=None):
        super().__init__("grep_code", "Search for code using regex patterns. More powerful than simple text search. Use this for finding specific code patterns, function definitions, or complex matches.", {
            "pattern": {
                "type": "string",
                "description": "Regular expression pattern to search for (e.g., 'def\\s+\\w+', 'class\\s+\\w+')"
            },
            "file_pattern": {
                "type": "string",
                "description": "Optional file pattern to filter search (e.g., '*.py'). Default searches all files.",
                "nullable": True
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return. Default is 20.",
                "nullable": True
            }
        }, metadata={
            "required_args": ["pattern"],
            "capability_tags": ["search", "regex"],
            "domain_tags": ["code"],
            "keywords": [
                "grep code",
                "regex search",
                "regular expression search",
                "pattern search",
                "search by regex",
            ],
            "usage_hint": "Use regex search when plain keyword search is too broad.",
        })
        self.main_window = main_window

    def execute(self, pattern=None, file_pattern=None, max_results=None):
        if not pattern or not pattern.strip():
            return {"error": "pattern is required"}
        
        try:
            import re
            
            results = []
            max_results = max_results or 20
            regex = re.compile(pattern.strip())
            
            for filepath, rel_path in _iter_code_files(file_pattern=file_pattern):
                if len(results) >= max_results:
                    break
                lines = _read_lines(filepath)
                if not lines:
                    continue
                matches = []
                for i, line in enumerate(lines, 1):
                    match = regex.search(line)
                    if match:
                        matches.append({
                            "line_number": i,
                            "content": line.rstrip(),
                            "match": match.group()
                        })
                if matches:
                    results.append({
                        "file": filepath,
                        "relative_path": rel_path,
                        "matches": matches[:5]
                    })
            
            return {
                "ok": True,
                "pattern": pattern,
                "total_files": len(results),
                "results": results
            }
        except Exception as e:
            return {"error": str(e)}


@register_tool
class FindSymbolTool(BaseTool):
    def __init__(self, main_window=None):
        super().__init__("find_symbol", "Find symbol definitions in the codebase. Best for locating Python classes, functions, methods, async functions, and top-level variables.", {
            "symbol": {
                "type": "string",
                "description": "Exact symbol name to find."
            },
            "file_pattern": {
                "type": "string",
                "description": "Optional glob filter such as '*.py' or 'plugins/**/*.py'.",
                "nullable": True
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of symbol definitions to return. Default is 20.",
                "nullable": True
            }
        }, metadata={
            "required_args": ["symbol"],
            "capability_tags": ["navigation", "symbol_lookup"],
            "domain_tags": ["code"],
            "keywords": [
                "find symbol",
                "find definition",
                "go to definition",
                "locate function",
                "locate class",
                "symbol lookup",
            ],
            "usage_hint": "Prefer this before editing code when you know the symbol name but not the file path.",
        })
        self.main_window = main_window

    def execute(self, symbol=None, file_pattern=None, max_results=None):
        if not symbol or not symbol.strip():
            return {"error": "symbol is required"}

        symbol = symbol.strip()
        max_results = max_results or 20
        results = []
        searched_files = 0

        for filepath, rel_path in _iter_code_files(file_pattern=file_pattern or "*.py"):
            if len(results) >= max_results:
                break
            searched_files += 1
            if not filepath.endswith(".py"):
                continue
            for item in _collect_python_symbols(filepath, rel_path):
                if item["name"] == symbol:
                    results.append(item)
                    if len(results) >= max_results:
                        break

        return {
            "ok": True,
            "symbol": symbol,
            "searched_files": searched_files,
            "total_matches": len(results),
            "results": results,
        }


@register_tool
class FindReferencesTool(BaseTool):
    def __init__(self, main_window=None):
        super().__init__("find_references", "Find references to a symbol across the codebase. For Python files, it classifies reference types such as import, call, inherit, attribute_access, and definition; for other code files it falls back to text matching.", {
            "symbol": {
                "type": "string",
                "description": "Exact symbol name to find references for."
            },
            "file_pattern": {
                "type": "string",
                "description": "Optional glob filter such as '*.py' or 'plugins/**/*.py'.",
                "nullable": True
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of reference matches to return. Default is 50.",
                "nullable": True
            }
        }, metadata={
            "required_args": ["symbol"],
            "capability_tags": ["navigation", "impact_analysis"],
            "domain_tags": ["code"],
            "keywords": [
                "find references",
                "find usages",
                "who calls this",
                "impact analysis",
                "call sites",
                "where used",
            ],
            "usage_hint": "Use after find_symbol to understand call sites and impact before changing code.",
        })
        self.main_window = main_window

    def execute(self, symbol=None, file_pattern=None, max_results=None):
        if not symbol or not symbol.strip():
            return {"error": "symbol is required"}

        symbol = symbol.strip()
        max_results = max_results or 50
        results = []
        searched_files = 0

        for filepath, rel_path in _iter_code_files(file_pattern=file_pattern):
            if len(results) >= max_results:
                break
            searched_files += 1
            if filepath.endswith(".py"):
                matches = _find_python_symbol_references(filepath, rel_path, symbol)
            else:
                matches = _find_text_references(filepath, rel_path, symbol)

            for match in matches:
                results.append(match)
                if len(results) >= max_results:
                    break

        return {
            "ok": True,
            "symbol": symbol,
            "searched_files": searched_files,
            "total_matches": len(results),
            "results": results,
        }
