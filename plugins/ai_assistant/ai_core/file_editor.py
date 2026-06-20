from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class PatchHunk:
    old_string: str
    new_string: str
    replace_all: bool = False


@dataclass(frozen=True)
class FileEditResult:
    ok: bool
    filepath: str
    summary: str = ""
    error: str = ""
    applied_hunks: int = 0
    created: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "ok": self.ok,
            "filepath": self.filepath,
            "summary": self.summary,
            "applied_hunks": self.applied_hunks,
            "created": self.created,
        }
        if self.error:
            payload["error"] = self.error
        if self.metadata:
            payload.update(self.metadata)
        return payload


class FileEditor:
    """Patch-first file editing boundary for the native PyLog agent runtime."""

    def __init__(self, project_root: Optional[str] = None, allowed_roots: Optional[Iterable[str]] = None):
        self.project_root = os.path.abspath(project_root or os.getcwd())
        roots = list(allowed_roots) if allowed_roots is not None else [self.project_root]
        self.allowed_roots = [self._normalize_path(root) for root in roots if str(root or "").strip()]

    def read_text(self, filepath: str) -> FileEditResult:
        resolved = self.resolve_path(filepath)
        access_error = self._validate_allowed_path(resolved)
        if access_error:
            return FileEditResult(ok=False, filepath=resolved, error=access_error)
        if not os.path.exists(resolved):
            return FileEditResult(ok=False, filepath=resolved, error=f"File not found: {resolved}")
        if not os.path.isfile(resolved):
            return FileEditResult(ok=False, filepath=resolved, error=f"Not a file: {resolved}")

        try:
            with open(resolved, "r", encoding="utf-8", errors="ignore") as handle:
                content = handle.read()
            return FileEditResult(
                ok=True,
                filepath=resolved,
                summary=f"Read {resolved}",
                metadata={"content": content},
            )
        except Exception as exc:
            return FileEditResult(ok=False, filepath=resolved, error=str(exc))

    def apply_patch(
        self,
        filepath: str,
        hunks: Iterable[PatchHunk | Dict[str, Any]],
        *,
        create_if_missing: bool = False,
    ) -> FileEditResult:
        prepared = self.prepare_patch(filepath, hunks, create_if_missing=create_if_missing)
        if not prepared.ok:
            return prepared

        resolved = prepared.filepath
        new_content = prepared.metadata.get("content", "")

        try:
            os.makedirs(os.path.dirname(resolved), exist_ok=True)
            with open(resolved, "w", encoding="utf-8") as handle:
                handle.write(new_content)

            existed = bool(prepared.metadata.get("existed"))
            action = "Created" if not existed else "Applied patch to"
            return FileEditResult(
                ok=True,
                filepath=resolved,
                summary=f"{action} {resolved}",
                applied_hunks=prepared.applied_hunks,
                created=not existed,
            )
        except Exception as exc:
            return FileEditResult(ok=False, filepath=resolved, error=str(exc))

    def prepare_patch(
        self,
        filepath: str,
        hunks: Iterable[PatchHunk | Dict[str, Any]],
        *,
        create_if_missing: bool = False,
    ) -> FileEditResult:
        """Build patched content without writing it to disk."""
        resolved = self.resolve_path(filepath)
        access_error = self._validate_allowed_path(resolved)
        if access_error:
            return FileEditResult(ok=False, filepath=resolved, error=access_error)

        normalized_hunks = self._normalize_hunks(hunks)
        if not normalized_hunks:
            return FileEditResult(ok=False, filepath=resolved, error="At least one patch hunk is required")

        exists = os.path.exists(resolved)
        if exists and not os.path.isfile(resolved):
            return FileEditResult(ok=False, filepath=resolved, error=f"Not a file: {resolved}")
        if not exists and not create_if_missing:
            return FileEditResult(ok=False, filepath=resolved, error=f"File not found: {resolved}")

        try:
            if exists:
                with open(resolved, "r", encoding="utf-8", errors="ignore") as handle:
                    content = handle.read()
            else:
                content = ""

            new_content, applied = self._apply_hunks(content, normalized_hunks, allow_create=not exists)
            if applied.error:
                return FileEditResult(
                    ok=False,
                    filepath=resolved,
                    error=applied.error,
                    applied_hunks=applied.count,
                )

            return FileEditResult(
                ok=True,
                filepath=resolved,
                summary=f"Prepared patch for {resolved}",
                applied_hunks=applied.count,
                created=not exists,
                metadata={"content": new_content, "existed": exists},
            )
        except Exception as exc:
            return FileEditResult(ok=False, filepath=resolved, error=str(exc))

    def resolve_path(self, filepath: str) -> str:
        candidate = str(filepath or "").strip()
        if not candidate:
            return self.project_root
        if not os.path.isabs(candidate):
            candidate = os.path.join(self.project_root, candidate)
        return self._normalize_path(candidate)

    def _validate_allowed_path(self, filepath: str) -> Optional[str]:
        if not self.allowed_roots:
            return None
        for root in self.allowed_roots:
            try:
                if os.path.commonpath([root, filepath]) == root:
                    return None
            except ValueError:
                continue
        return f"Access denied: {filepath} is outside allowed roots"

    @staticmethod
    def _normalize_hunks(hunks: Iterable[PatchHunk | Dict[str, Any]]) -> List[PatchHunk]:
        normalized = []
        for hunk in hunks or []:
            if isinstance(hunk, PatchHunk):
                normalized.append(hunk)
                continue
            if isinstance(hunk, dict):
                normalized.append(
                    PatchHunk(
                        old_string=str(hunk.get("old_string", "")),
                        new_string=str(hunk.get("new_string", "")),
                        replace_all=bool(hunk.get("replace_all", False)),
                    )
                )
        return normalized

    @classmethod
    def _apply_hunks(cls, content: str, hunks: List[PatchHunk], *, allow_create: bool):
        result = _PatchApplyCounter()
        for index, hunk in enumerate(hunks, start=1):
            if allow_create and len(hunks) == 1 and hunk.old_string == "":
                result.count += 1
                return hunk.new_string, result

            if not hunk.old_string:
                result.error = f"Hunk {index} old_string is required unless creating a file"
                return content, result

            if hunk.old_string not in content:
                result.error = f"Hunk {index} old_string not found in file"
                return content, result

            if hunk.replace_all:
                occurrences = content.count(hunk.old_string)
                content = content.replace(hunk.old_string, hunk.new_string)
                result.count += occurrences
            else:
                content = content.replace(hunk.old_string, hunk.new_string, 1)
                result.count += 1
        return content, result

    @staticmethod
    def _normalize_path(path: str) -> str:
        return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))


@dataclass
class _PatchApplyCounter:
    count: int = 0
    error: str = ""
