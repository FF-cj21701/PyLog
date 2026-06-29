from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence


@dataclass
class ShellExecutionResult:
    ok: bool
    command: str
    argv: List[str]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    summary: str
    timed_out: bool = False
    blocked: bool = False
    verification: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        payload = {
            "ok": self.ok,
            "command": self.command,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "summary": self.summary,
            "timed_out": self.timed_out,
            "blocked": self.blocked,
            "verification": self.verification,
        }
        if self.error:
            payload["error"] = self.error
        return payload


class ControlledShellExecutor:
    """Run local commands through a small safety and result-normalization boundary."""

    SHELL_CONTROL_TOKENS = ("&&", "||", "|", ";", ">", "<", "`", "$(")
    DESTRUCTIVE_PATTERNS = (
        ("rm", "-rf"),
        ("rm", "-fr"),
        ("rmdir", "/s"),
        ("del", "/s"),
        ("git", "reset", "--hard"),
        ("git", "checkout"),
        ("git", "restore"),
        ("git", "clean"),
        ("git", "revert"),
    )
    PACKAGE_INSTALLERS = (
        ("pip", "install"),
        ("python", "-m", "pip", "install"),
        ("py", "-m", "pip", "install"),
        ("npm", "install"),
        ("pnpm", "install"),
        ("yarn", "add"),
    )
    VERIFICATION_COMMANDS = {
        "pytest",
        "ruff",
        "black",
        "mypy",
        "py_compile",
        "compileall",
    }

    def __init__(self, project_root: str | os.PathLike | None = None, timeout_seconds: int = 30, output_limit: int = 4000):
        self.project_root = Path(project_root or self._default_project_root()).resolve()
        self.timeout_seconds = timeout_seconds
        self.output_limit = output_limit

    def run(
        self,
        command: str | Sequence[str],
        *,
        cwd: str | os.PathLike | None = None,
        timeout_seconds: int | None = None,
        allow_shell: bool = False,
    ) -> ShellExecutionResult:
        cwd_path = self._resolve_cwd(cwd)
        command_text = self._stringify_command(command)
        argv_result = self._normalize_command(command, allow_shell=allow_shell)
        if isinstance(argv_result, ShellExecutionResult):
            return argv_result
        argv = argv_result

        block_reason = self._blocked_reason(argv, command_text, allow_shell=allow_shell)
        if block_reason:
            return ShellExecutionResult(
                ok=False,
                command=command_text,
                argv=argv,
                cwd=str(cwd_path),
                exit_code=-1,
                stdout="",
                stderr=block_reason,
                summary=f"Command blocked: {block_reason}",
                blocked=True,
                error=block_reason,
                verification=self._is_verification_command(argv),
            )

        try:
            proc = subprocess.run(
                argv if not allow_shell else command_text,
                cwd=str(cwd_path),
                capture_output=True,
                text=True,
                timeout=timeout_seconds or self.timeout_seconds,
                shell=allow_shell,
            )
            stdout = self._truncate(proc.stdout or "")
            stderr = self._truncate(proc.stderr or "")
            ok = proc.returncode == 0
            return ShellExecutionResult(
                ok=ok,
                command=command_text,
                argv=argv,
                cwd=str(cwd_path),
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                summary="Command succeeded" if ok else f"Command failed with exit code {proc.returncode}",
                verification=self._is_verification_command(argv),
            )
        except subprocess.TimeoutExpired as exc:
            return ShellExecutionResult(
                ok=False,
                command=command_text,
                argv=argv,
                cwd=str(cwd_path),
                exit_code=-1,
                stdout=self._truncate(exc.stdout or ""),
                stderr=self._truncate(exc.stderr or ""),
                summary=f"Command timed out after {timeout_seconds or self.timeout_seconds}s",
                timed_out=True,
                verification=self._is_verification_command(argv),
                error="timeout",
            )
        except Exception as exc:
            return ShellExecutionResult(
                ok=False,
                command=command_text,
                argv=argv,
                cwd=str(cwd_path),
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                summary=str(exc),
                verification=self._is_verification_command(argv),
                error=str(exc),
            )

    def _normalize_command(self, command: str | Sequence[str], *, allow_shell: bool):
        if isinstance(command, str):
            text = command.strip()
            if not text:
                return self._blocked_empty(text)
            if not allow_shell and any(token in text for token in self.SHELL_CONTROL_TOKENS):
                return ShellExecutionResult(
                    ok=False,
                    command=text,
                    argv=[],
                    cwd=str(self.project_root),
                    exit_code=-1,
                    stdout="",
                    stderr="Shell control operators are not allowed in controlled command mode.",
                    summary="Command blocked: shell control operators are not allowed",
                    blocked=True,
                    error="Shell control operators are not allowed in controlled command mode.",
                )
            try:
                argv = shlex.split(text, posix=True)
            except ValueError as exc:
                return ShellExecutionResult(
                    ok=False,
                    command=text,
                    argv=[],
                    cwd=str(self.project_root),
                    exit_code=-1,
                    stdout="",
                    stderr=str(exc),
                    summary=f"Command parse failed: {exc}",
                    blocked=True,
                    error=str(exc),
                )
            return argv

        argv = [str(part) for part in command if str(part).strip()]
        if not argv:
            return self._blocked_empty("")
        return argv

    def _blocked_empty(self, command: str) -> ShellExecutionResult:
        return ShellExecutionResult(
            ok=False,
            command=command,
            argv=[],
            cwd=str(self.project_root),
            exit_code=-1,
            stdout="",
            stderr="command is required",
            summary="Command blocked: command is required",
            blocked=True,
            error="command is required",
        )

    def _blocked_reason(self, argv: Sequence[str], command_text: str, *, allow_shell: bool) -> str | None:
        lowered = [part.lower() for part in argv]
        compact = " ".join(lowered)

        for pattern in self.DESTRUCTIVE_PATTERNS:
            if self._matches_pattern(lowered, pattern):
                return f"Destructive command is blocked: {' '.join(pattern)}"
        for pattern in self.PACKAGE_INSTALLERS:
            if self._matches_pattern(lowered, pattern):
                return f"Package installation requires explicit approval: {' '.join(pattern)}"

        if allow_shell:
            for token in self.SHELL_CONTROL_TOKENS:
                if token in command_text and any(word in compact for word in ("rm ", "del ", "reset --hard", "clean ")):
                    return "Dangerous shell command sequence is blocked"
        return None

    def _resolve_cwd(self, cwd: str | os.PathLike | None) -> Path:
        if cwd is None:
            return self.project_root
        path = Path(cwd).expanduser()
        if not path.is_absolute():
            path = self.project_root / path
        return path.resolve()

    def _is_verification_command(self, argv: Sequence[str]) -> bool:
        lowered = [part.lower() for part in argv]
        if not lowered:
            return False
        if lowered[0] in self.VERIFICATION_COMMANDS:
            return True
        return len(lowered) >= 3 and lowered[1] == "-m" and lowered[2] in self.VERIFICATION_COMMANDS

    def _truncate(self, text: str) -> str:
        if len(text) <= self.output_limit:
            return text
        return text[: self.output_limit] + "\n...[truncated]"

    @staticmethod
    def _matches_pattern(argv: Sequence[str], pattern: Sequence[str]) -> bool:
        if len(argv) < len(pattern):
            return False
        return tuple(argv[: len(pattern)]) == tuple(pattern)

    @staticmethod
    def _stringify_command(command: str | Sequence[str]) -> str:
        if isinstance(command, str):
            return command.strip()
        return " ".join(str(part) for part in command)

    @staticmethod
    def _default_project_root() -> Path:
        return Path(__file__).resolve().parents[3]
