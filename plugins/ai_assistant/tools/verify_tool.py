import os
import shlex
import shutil
import subprocess
import sys
import importlib
from tempfile import NamedTemporaryFile
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None

try:
    from .base_tool import BaseTool
    from .registry import register_tool
except ImportError:
    try:
        from plugins.ai_assistant.tools.base_tool import BaseTool
        from plugins.ai_assistant.tools.registry import register_tool
    except ImportError:
        BaseTool = importlib.import_module("base_tool").BaseTool
        register_tool = importlib.import_module("registry").register_tool

try:
    from ..common.paths import PathResolver
except ImportError:
    try:
        from plugins.ai_assistant.common.paths import PathResolver
    except ImportError:
        try:
            PathResolver = importlib.import_module("paths").PathResolver
        except ImportError:
            PathResolver = None

try:
    from ..runtime.script_job_manager import get_script_job_manager
except ImportError:
    try:
        from plugins.ai_assistant.runtime.script_job_manager import get_script_job_manager
    except ImportError:
        get_script_job_manager = None

try:
    from ..ai_core.shell_executor import ControlledShellExecutor
except ImportError:
    try:
        from plugins.ai_assistant.ai_core.shell_executor import ControlledShellExecutor
    except ImportError:
        ControlledShellExecutor = importlib.import_module("shell_executor").ControlledShellExecutor


def _project_root():
    if PathResolver:
        return PathResolver.get_project_root()
    return os.getcwd()


def _is_scripts_user_workspace():
    if not PathResolver or not hasattr(PathResolver, "is_scripts_user_workspace"):
        return False
    try:
        return bool(PathResolver.is_scripts_user_workspace())
    except Exception:
        return False


def _workspace_command_root(cwd=None):
    if cwd:
        return cwd
    if _is_scripts_user_workspace() and PathResolver:
        return PathResolver.get_scripts_user_dir()
    return _project_root()


def _read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return ""


def _exists(root, *parts):
    return Path(root, *parts).exists()


def _load_pyproject(root):
    path = Path(root, "pyproject.toml")
    if not path.exists() or tomllib is None:
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def detect_project_commands(cwd=None):
    root = _workspace_command_root(cwd)
    pyproject = _load_pyproject(root)
    requirements = _read_text(Path(root, "requirements.txt"))
    package_json = _read_text(Path(root, "package.json"))
    setup_cfg = _read_text(Path(root, "setup.cfg"))
    makefile = _read_text(Path(root, "Makefile"))

    evidence = []
    commands = {
        "test": None,
        "lint": None,
        "format": None,
    }

    if package_json:
        evidence.append("package.json")
    if _exists(root, "pytest.ini"):
        evidence.append("pytest.ini")
        commands["test"] = "pytest"
    if _exists(root, "tests"):
        evidence.append("tests/")
        commands["test"] = commands["test"] or "pytest"
    if _exists(root, "pyproject.toml"):
        evidence.append("pyproject.toml")
    if _exists(root, "ruff.toml"):
        evidence.append("ruff.toml")
        commands["lint"] = "ruff check"
        commands["format"] = "ruff format --check"
    if _exists(root, "requirements.txt"):
        evidence.append("requirements.txt")
    if _exists(root, "Makefile"):
        evidence.append("Makefile")
    if _exists(root, "setup.cfg"):
        evidence.append("setup.cfg")

    pyproject_text = _read_text(Path(root, "pyproject.toml"))
    combined_python_text = "\n".join([requirements, setup_cfg, pyproject_text]).lower()

    if "pytest" in combined_python_text:
        commands["test"] = commands["test"] or "pytest"
    if "ruff" in combined_python_text:
        commands["lint"] = commands["lint"] or "ruff check"
        commands["format"] = commands["format"] or "ruff format --check"
    if "black" in combined_python_text:
        commands["format"] = commands["format"] or "black --check ."

    if not any(commands.values()) and _exists(root, "requirements.txt"):
        commands["lint"] = "python -m py_compile"

    if makefile:
        lowered = makefile.lower()
        if "\ntest:" in lowered or lowered.startswith("test:"):
            commands["test"] = commands["test"] or "make test"
        if "\nlint:" in lowered or lowered.startswith("lint:"):
            commands["lint"] = commands["lint"] or "make lint"
        if "\nformat:" in lowered or lowered.startswith("format:"):
            commands["format"] = commands["format"] or "make format"

    return {
        "ok": True,
        "project_root": root,
        "detected_commands": commands,
        "evidence": evidence,
        "workspace_scope": "scripts_user" if _is_scripts_user_workspace() else "project",
        "project_type": "python" if any(e in evidence for e in ["requirements.txt", "pyproject.toml", "pytest.ini", "tests/"]) else "unknown",
    }


def _run_command(command, cwd=None):
    return ControlledShellExecutor(project_root=_project_root(), timeout_seconds=60).run(
        command,
        cwd=cwd or _project_root(),
        allow_shell=False,
    ).to_dict()


def _looks_like_interactive_plot_script(filepath):
    source = _read_text(filepath).lower()
    if not source:
        return False

    interactive_markers = (
        "matplotlib.pyplot",
        "plt.show(",
        ".show()",
        "pyplot.show(",
    )
    return any(marker in source for marker in interactive_markers)


def _run_detached_command(command, cwd=None):
    stdout_log = NamedTemporaryFile(prefix="pylog_ai_plot_", suffix=".log", delete=False)
    stderr_log = NamedTemporaryFile(prefix="pylog_ai_plot_", suffix=".err", delete=False)
    stdout_path = stdout_log.name
    stderr_path = stderr_log.name
    stdout_log.close()
    stderr_log.close()

    stdout_handle = None
    stderr_handle = None
    try:
        stdout_handle = open(stdout_path, "w", encoding="utf-8")
        stderr_handle = open(stderr_path, "w", encoding="utf-8")
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUTF8", "1")
        kwargs = {
            "cwd": cwd or _project_root(),
            "stdout": stdout_handle,
            "stderr": stderr_handle,
            "stdin": subprocess.DEVNULL,
            "shell": False,
            "start_new_session": True,
            "env": env,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)

        proc = subprocess.Popen(command, **kwargs)
        stdout_handle.close()
        stderr_handle.close()
        return {
            "ok": True,
            "command": " ".join(command),
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "summary": "Interactive plot script launched in background",
            "background": True,
            "pid": proc.pid,
            "stdout_log": stdout_path,
            "stderr_log": stderr_path,
        }
    except Exception as e:
        try:
            stdout_handle.close()
        except Exception:
            pass
        try:
            stderr_handle.close()
        except Exception:
            pass
        return {
            "ok": False,
            "command": " ".join(command),
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e),
            "summary": str(e),
            "error": str(e),
            "background": False,
        }


def _select_background_python_executable():
    if os.name != "nt":
        return sys.executable

    current = Path(sys.executable)
    candidate_names = []
    if current.name.lower() == "python.exe":
        candidate_names.append(current.with_name("pythonw.exe"))
    candidate_names.append(current.parent / "pythonw.exe")

    seen = set()
    for candidate in candidate_names:
        normalized = str(candidate).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        if candidate.exists():
            return str(candidate)

    return sys.executable


def _resolve_path(filepath):
    if not filepath:
        return None
    return filepath if os.path.isabs(filepath) else os.path.join(_project_root(), filepath)


def _normalize_relative_path(filepath):
    if not filepath:
        return None
    try:
        return str(Path(filepath).resolve().relative_to(Path(_project_root()).resolve())).replace("\\", "/")
    except Exception:
        return str(filepath).replace("\\", "/")


def _command_exists(name):
    return shutil.which(name) is not None


def _resolve_test_command(normalized):
    try:
        parts = shlex.split(normalized)
    except ValueError:
        return None
    if not parts:
        return None
    if parts[0] == "pytest":
        args = parts[1:]
        if _command_exists("pytest"):
            return ["pytest", *args]
        return [sys.executable, "-m", "pytest", *args]
    if parts[:3] == ["python", "-m", "pytest"]:
        return [sys.executable, "-m", "pytest", *parts[3:]]
    return None


def _resolve_lint_command(normalized, target=None):
    if normalized == "ruff check":
        if _command_exists("ruff"):
            return ["ruff", "check"]
        return [sys.executable, "-m", "ruff", "check"]
    if normalized == "python -m py_compile":
        if not target:
            return None
        resolved = _resolve_path(target)
        return [sys.executable, "-m", "py_compile", resolved]
    return None


def _resolve_format_command(normalized):
    if normalized == "ruff format --check":
        if _command_exists("ruff"):
            return ["ruff", "format", "--check"]
        return [sys.executable, "-m", "ruff", "format", "--check"]
    if normalized == "black --check .":
        if _command_exists("black"):
            return ["black", "--check", "."]
        return [sys.executable, "-m", "black", "--check", "."]
    return None


def _is_script_target(filepath):
    normalized = str(filepath or "").replace("\\", "/").lower()
    if not normalized:
        return False
    return (
        "/scripts_user/" in normalized
        or normalized.startswith("scripts_user/")
        or "/scripts/" in normalized
        or normalized.startswith("scripts/")
    ) and normalized.endswith(".py")


def _is_scripts_user_target(filepath):
    normalized = str(filepath or "").replace("\\", "/").lower()
    if not normalized:
        return False
    return (
        "/scripts_user/" in normalized
        or normalized.startswith("scripts_user/")
    ) and normalized.endswith(".py")


def _is_bare_pytest_command(normalized):
    try:
        parts = shlex.split(str(normalized or "").strip())
    except ValueError:
        return False
    return parts == ["pytest"] or parts == ["python", "-m", "pytest"]


def verify_target(filepath=None, cwd=None, run_execution=False):
    if filepath:
        resolved = _resolve_path(filepath)
        normalized = _normalize_relative_path(resolved)
        if not os.path.exists(resolved):
            return {
                "ok": False,
                "target_type": "missing",
                "filepath": normalized or filepath,
                "summary": f"Target file does not exist: {filepath}",
                "error": f"Target file does not exist: {filepath}",
            }

        if _is_scripts_user_workspace() and not _is_scripts_user_target(normalized or resolved):
            return {
                "ok": False,
                "target_type": "blocked",
                "filepath": normalized or filepath,
                "workspace_scope": "scripts_user",
                "blocked": True,
                "summary": "scripts_user workspace only allows verification of scripts_user Python files.",
                "error": "scripts_user workspace only allows verification of scripts_user Python files.",
            }

        if _is_script_target(normalized or resolved):
            steps = []
            import_result = _run_command(
                [sys.executable, "-m", "py_compile", resolved],
                cwd=cwd or _project_root(),
            )
            steps.append({
                "name": "import_check",
                "tool": "run_import_check",
                "result": import_result,
            })
            if not import_result.get("ok"):
                return {
                    "ok": False,
                    "target_type": "script",
                    "filepath": normalized,
                    "strategy": "script",
                    "steps": steps,
                    "summary": f"Script verification failed at import check for {normalized}",
                    "recommended_next_tool": "run_import_check",
                }

            if run_execution:
                run_result = _run_command([sys.executable, resolved], cwd=cwd or _project_root())
                steps.append({
                    "name": "run_file",
                    "tool": "run_python_file",
                    "result": run_result,
                })
                return {
                    "ok": bool(run_result.get("ok")),
                    "target_type": "script",
                    "filepath": normalized,
                    "strategy": "script",
                    "steps": steps,
                    "summary": (
                        f"Script verification passed for {normalized}"
                        if run_result.get("ok")
                        else f"Script execution failed for {normalized}"
                    ),
                    "recommended_next_tool": None if run_result.get("ok") else "run_python_file",
                }

            return {
                "ok": True,
                "target_type": "script",
                "filepath": normalized,
                "strategy": "script",
                "steps": steps,
                "summary": f"Script import check passed for {normalized}",
                "recommended_next_tool": "run_python_file",
            }

    if _is_scripts_user_workspace():
        detected = detect_project_commands(cwd=cwd)
        return {
            "ok": False,
            "target_type": "workspace",
            "strategy": "scripts_user",
            "project_root": detected["project_root"],
            "detected_commands": detected["detected_commands"],
            "workspace_scope": "scripts_user",
            "blocked": True,
            "summary": "scripts_user workspace requires a scripts_user Python filepath for verification.",
            "error": "scripts_user workspace requires a scripts_user Python filepath for verification.",
            "recommended_next_tool": "verify_target",
        }

    detected = detect_project_commands(cwd=cwd)
    command = detected["detected_commands"].get("test")
    if not command:
        return {
            "ok": False,
            "target_type": "project",
            "strategy": "project",
            "project_root": detected["project_root"],
            "detected_commands": detected["detected_commands"],
            "summary": "No project test command detected. Try detect_project_commands or run a target-specific verification.",
            "error": "No project test command detected",
        }

    resolved_command = _resolve_test_command(command)
    if not resolved_command:
        return {
            "ok": False,
            "target_type": "project",
            "strategy": "project",
            "project_root": detected["project_root"],
            "detected_commands": detected["detected_commands"],
            "summary": f"Detected unsupported test command: {command}",
            "error": f"Detected unsupported test command: {command}",
        }

    result = _run_command(resolved_command, cwd=cwd or _project_root())
    return {
        "ok": bool(result.get("ok")),
        "target_type": "project",
        "strategy": "project",
        "project_root": detected["project_root"],
        "detected_commands": detected["detected_commands"],
        "steps": [{
            "name": "project_test",
            "tool": "run_test_command",
            "result": result,
        }],
        "summary": (
            f"Project verification passed with `{command}`"
            if result.get("ok")
            else f"Project verification failed with `{command}`"
        ),
        "recommended_next_tool": None if result.get("ok") else "run_test_command",
    }


@register_tool
class RunPythonFileTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "run_python_file",
            "Run a Python file with the current Python interpreter and capture structured output. PyLog scripts run in a managed child process by default so they can time out or be cancelled.",
            {
                "filepath": {
                    "type": "string",
                    "description": "Path to the Python file."
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory.",
                    "nullable": True
                }
            },
            metadata={
                "side_effect_level": "execution",
                "is_verification_tool": True,
                "required_args": ["filepath"],
                "path_argument_names": ["filepath"],
                "risk_level": "medium",
                "output_type": "verification",
                "capability_tags": ["verification", "python_execution"],
                "domain_tags": ["code", "script"],
                "keywords": [
                    "run python file",
                    "execute python script",
                    "run script file",
                    "python execution",
                    "verify script output",
                ],
                "usage_hint": "Use to execute a Python file and capture structured verification output. PyLog scripts run out-of-process; use plot-spec tools for UI plotting.",
            }
        )
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, filepath=None, cwd=None):
        if not filepath:
            return {"ok": False, "error": "filepath is required"}
        
        target = _resolve_path(filepath)
        normalized = _normalize_relative_path(target)
        
        if _is_script_target(normalized) and get_script_job_manager:
            manager = get_script_job_manager(_project_root())
            result = manager.run_script(
                script_path=target,
                cwd=cwd or _project_root(),
                execution_mode="quick",
                timeout_seconds=60,
            )
            result["target_type"] = "script"
            result["strategy"] = "managed_child_process"
            result["summary"] = (
                f"PyLog script executed successfully in managed child process: {normalized}"
                if result.get("ok")
                else f"PyLog script execution failed in managed child process: {normalized}"
            )
            return result

        # Original out-of-process execution for non-PyLog scripts or when no executor is available
        if _looks_like_interactive_plot_script(target):
            background_python = _select_background_python_executable()
            result = _run_detached_command([background_python, target], cwd=cwd or _project_root())
            if result.get("ok"):
                result["target_type"] = "script"
                result["strategy"] = "background_execution"
                result["python_executable"] = background_python
                result["summary"] = (
                    "Interactive plotting script launched in background. "
                    "The tool call completed without waiting for the plot window to close."
                )
                stdout_log = result.get("stdout_log")
                stderr_log = result.get("stderr_log")
                follow_up = []
                if stdout_log:
                    follow_up.append(f"stdout log: {stdout_log}")
                if stderr_log:
                    follow_up.append(f"stderr log: {stderr_log}")
                if follow_up:
                    result["summary"] += "\n" + "\n".join(follow_up)
                result["message"] = (
                    "Background plot launch succeeded. "
                    "Do not rerun the script in terminal just to inspect output; read the generated log files instead."
                )
                result["recommended_next_tool"] = "read_file"
            return result
        
        return _run_command([sys.executable, target], cwd=cwd or _project_root())

@register_tool
class DetectProjectCommandsTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "detect_project_commands",
            "Detect recommended project test, lint, and format commands based on repository files.",
            {
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory to inspect.",
                    "nullable": True
                }
            },
            metadata={
                "side_effect_level": "none",
                "risk_level": "low",
                "output_type": "structured_data",
                "capability_tags": ["detection", "project_introspection"],
                "domain_tags": ["code"],
                "keywords": [
                    "detect test command",
                    "detect lint command",
                    "detect format command",
                    "project commands",
                    "test command discovery",
                ],
                "usage_hint": "Use before manual test/lint selection when project commands are unknown.",
            }
        )

    def execute(self, cwd=None):
        return detect_project_commands(cwd=cwd)


@register_tool
class VerifyTargetTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "verify_target",
            "Verify a changed target using the best default strategy: script-level checks for script files, or detected project tests for source changes.",
            {
                "filepath": {
                    "type": "string",
                    "description": "Optional changed file path. Script files use import/run checks; other targets fall back to project verification.",
                    "nullable": True
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory.",
                    "nullable": True
                },
                "run_execution": {
                    "type": "boolean",
                    "description": "For script files, also execute the file after import check.",
                    "nullable": True
                }
            },
            metadata={
                "side_effect_level": "execution",
                "is_verification_tool": True,
                "path_argument_names": ["filepath"],
                "risk_level": "medium",
                "output_type": "verification",
                "capability_tags": ["verification", "auto_strategy"],
                "domain_tags": ["code", "script"],
                "search_weight": 8,
                "preferred_for": [
                    "verify file",
                    "verify target",
                    "check changed code",
                    "validate script",
                    "run verification",
                ],
                "keywords": [
                    "verify target",
                    "verify file",
                    "run verification",
                    "test changed file",
                    "validate script",
                    "check changed code",
                ],
                "usage_hint": "Preferred first verification step after file changes.",
            }
        )

    def execute(self, filepath=None, cwd=None, run_execution=False):
        return verify_target(filepath=filepath, cwd=cwd, run_execution=run_execution)


@register_tool
class RunTestCommandTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "run_test_command",
            "Run a controlled Python test command. Prefer this after code changes.",
            {
                "command": {
                    "type": "string",
                    "description": "Optional test command. Supported: pytest, python -m pytest.",
                    "nullable": True
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory.",
                    "nullable": True
                }
            },
            metadata={
                "side_effect_level": "execution",
                "is_verification_tool": True,
                "risk_level": "medium",
                "output_type": "verification",
                "capability_tags": ["verification", "tests"],
                "domain_tags": ["code"],
                "search_weight": 6,
                "preferred_for": [
                    "run tests",
                    "pytest",
                    "unit tests",
                    "test command",
                ],
                "keywords": [
                    "run tests",
                    "pytest",
                    "test command",
                    "execute tests",
                    "run unit tests",
                ],
                "usage_hint": "Use for controlled test execution when a test command is known or detected.",
            }
        )

    def execute(self, command=None, cwd=None):
        if _is_scripts_user_workspace() and not command:
            detected = detect_project_commands(cwd=cwd)
            return {
                "ok": False,
                "blocked": True,
                "workspace_scope": "scripts_user",
                "detected_commands": detected.get("detected_commands", {}),
                "summary": "scripts_user workspace blocks default project test execution. Pass a focused pytest command explicitly or verify a scripts_user file.",
                "error": "scripts_user workspace blocks default project test execution.",
                "recommended_next_tool": "verify_target",
            }
        detected = detect_project_commands(cwd=cwd)
        normalized = (command or detected["detected_commands"].get("test") or "pytest").strip()
        if _is_scripts_user_workspace() and _is_bare_pytest_command(normalized):
            return {
                "ok": False,
                "blocked": True,
                "workspace_scope": "scripts_user",
                "summary": "scripts_user workspace blocks bare pytest. Use a focused pytest target or verify a scripts_user file.",
                "error": "scripts_user workspace blocks bare pytest.",
                "recommended_next_tool": "verify_target",
            }
        resolved_command = _resolve_test_command(normalized)
        if not resolved_command:
            return {"ok": False, "error": f"Unsupported test command: {normalized}"}
        return _run_command(resolved_command, cwd=cwd or _project_root())


@register_tool
class RunLintCommandTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "run_lint_command",
            "Run a controlled lint command. Supported: ruff check, python -m py_compile <file>.",
            {
                "command": {
                    "type": "string",
                    "description": "Lint command name.",
                    "nullable": True
                },
                "target": {
                    "type": "string",
                    "description": "Optional file target for py_compile.",
                    "nullable": True
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory.",
                    "nullable": True
                }
            },
            metadata={
                "side_effect_level": "execution",
                "is_verification_tool": True,
                "argument_rules": [
                    {
                        "type": "requires_when",
                        "arg": "command",
                        "equals": "python -m py_compile",
                        "requires": "target",
                    }
                ],
                "path_argument_names": ["target"],
                "risk_level": "medium",
                "output_type": "verification",
                "capability_tags": ["verification", "lint"],
                "domain_tags": ["code"],
                "search_weight": 5,
                "preferred_for": [
                    "run lint",
                    "syntax check",
                    "compile check",
                    "py_compile",
                ],
                "keywords": [
                    "run lint",
                    "lint command",
                    "ruff check",
                    "py_compile",
                    "syntax check",
                    "compile check",
                ],
                "usage_hint": "Use for linting or compile checks, especially py_compile on a changed file.",
            }
        )

    def execute(self, command=None, target=None, cwd=None):
        detected = detect_project_commands(cwd=cwd)
        normalized = (command or detected["detected_commands"].get("lint") or "ruff check").strip()
        resolved_command = _resolve_lint_command(normalized, target=target)
        if normalized == "python -m py_compile" and not target:
            return {"ok": False, "error": "target is required for python -m py_compile"}
        if resolved_command:
            return _run_command(resolved_command, cwd=cwd or _project_root())
        return {"ok": False, "error": f"Unsupported lint command: {normalized}"}


@register_tool
class RunFormatCommandTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "run_format_command",
            "Run a controlled format check command. Supported: ruff format --check, black --check .",
            {
                "command": {
                    "type": "string",
                    "description": "Format command name.",
                    "nullable": True
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory.",
                    "nullable": True
                }
            },
            metadata={
                "side_effect_level": "execution",
                "is_verification_tool": True,
                "risk_level": "medium",
                "output_type": "verification",
                "capability_tags": ["verification", "format_check"],
                "domain_tags": ["code"],
                "search_weight": 4,
                "preferred_for": [
                    "format check",
                    "check formatting",
                    "formatter check",
                ],
                "keywords": [
                    "format check",
                    "run formatter check",
                    "ruff format",
                    "black check",
                    "check formatting",
                ],
                "usage_hint": "Use to confirm formatting compliance without mutating source files.",
            }
        )

    def execute(self, command=None, cwd=None):
        detected = detect_project_commands(cwd=cwd)
        normalized = (command or detected["detected_commands"].get("format") or "ruff format --check").strip()
        resolved_command = _resolve_format_command(normalized)
        if resolved_command:
            return _run_command(resolved_command, cwd=cwd or _project_root())
        return {"ok": False, "error": f"Unsupported format command: {normalized}"}


@register_tool
class RunImportCheckTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "run_import_check",
            "Run a Python import/compile check for a target file.",
            {
                "filepath": {
                    "type": "string",
                    "description": "Path to the Python file."
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory.",
                    "nullable": True
                }
            },
            metadata={
                "side_effect_level": "execution",
                "is_verification_tool": True,
                "required_args": ["filepath"],
                "path_argument_names": ["filepath"],
                "risk_level": "low",
                "output_type": "verification",
                "capability_tags": ["verification", "import_check"],
                "domain_tags": ["code", "script"],
                "keywords": [
                    "import check",
                    "compile python file",
                    "syntax check python",
                    "py_compile",
                    "check imports",
                ],
                "usage_hint": "Use as a fast syntax/import check before running a Python file.",
            }
        )

    def execute(self, filepath=None, cwd=None):
        if not filepath:
            return {"ok": False, "error": "filepath is required"}
        resolved = _resolve_path(filepath)
        return _run_command([sys.executable, "-m", "py_compile", resolved], cwd=cwd or _project_root())
