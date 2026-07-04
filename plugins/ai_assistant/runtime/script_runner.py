from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import traceback


def _load_payload(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _project_root_from_payload(payload: dict) -> str:
    root = payload.get("project_root")
    if root:
        return os.path.abspath(str(root))
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _read_code(payload: dict) -> tuple[str, str]:
    code = payload.get("code")
    if code:
        return str(code), payload.get("script_path") or "<inline>"
    script_path = payload.get("script_path")
    if not script_path:
        raise ValueError("payload must include code or script_path")
    with open(script_path, "r", encoding="utf-8") as handle:
        return handle.read(), script_path


def _jsonable_action(action) -> dict:
    if not isinstance(action, dict):
        raise TypeError("ui action must be a dict")
    # Round-trip through JSON to enforce a child-process-safe payload contract.
    return json.loads(json.dumps(action, ensure_ascii=False))


def _build_context(
    payload: dict,
    project_root: str,
    filename: str,
    stdout_buffer: io.StringIO,
    ui_actions: list,
) -> dict:
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    import numpy as np
    from scripts.data.db_manager import DBManager

    db_path = payload.get("db_path") or ""
    db = DBManager(db_path, ensure_schema=False) if db_path else None
    def emit_ui_action(action):
        ui_actions.append(_jsonable_action(action))
        return action

    return {
        "__name__": "__main__",
        "__file__": filename,
        "db_path": db_path,
        "db": db,
        "app": None,
        "np": np,
        "DBManager": DBManager,
        "wells": payload.get("wells") or [],
        "ui_actions": ui_actions,
        "emit_ui_action": emit_ui_action,
        "print": lambda *args, **kwargs: print(*args, file=stdout_buffer, **kwargs),
    }


def run_payload(payload: dict) -> dict:
    project_root = _project_root_from_payload(payload)
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    exit_code = 0
    ok = True
    error = None
    ui_actions = []

    try:
        code, filename = _read_code(payload)
        context = _build_context(payload, project_root, filename, stdout_buffer, ui_actions)
        original_exit = sys.exit

        def intercepted_exit(*args, **_kwargs):
            raise SystemExit(args[0] if args else 0)

        sys.exit = intercepted_exit
        try:
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                exec(code, context)
        except SystemExit as exc:
            exit_code = int(exc.code) if isinstance(exc.code, int) else 0
            ok = exit_code == 0
            if not ok:
                error = f"Script exited with code {exit_code}"
        finally:
            sys.exit = original_exit
        ui_actions = [_jsonable_action(action) for action in context.get("ui_actions", ui_actions)]
    except Exception as exc:
        ok = False
        exit_code = 1
        error = str(exc)
        stderr_buffer.write(traceback.format_exc())

    return {
        "ok": ok,
        "stdout": stdout_buffer.getvalue(),
        "stderr": stderr_buffer.getvalue(),
        "exit_code": exit_code,
        "error": error,
        "ui_actions": ui_actions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PyLog AI script payload in a child process.")
    parser.add_argument("--payload", required=True)
    args = parser.parse_args()
    result = run_payload(_load_payload(args.payload))
    print("__PYLOG_SCRIPT_RESULT__" + json.dumps(result, ensure_ascii=False))
    return int(result.get("exit_code") or 0)


if __name__ == "__main__":
    raise SystemExit(main())
