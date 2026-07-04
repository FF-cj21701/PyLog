from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


RESULT_MARKER = "__PYLOG_SCRIPT_RESULT__"


@dataclass
class ScriptJob:
    job_id: str
    mode: str
    payload_path: str
    process: subprocess.Popen
    started_at: float
    timeout_seconds: int
    command: list[str]
    status: str = "running"
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    timed_out: bool = False
    cancelled: bool = False
    error: Optional[str] = None
    completed_at: Optional[float] = None
    result_payload: Dict[str, Any] = field(default_factory=dict)
    ui_actions: list[Dict[str, Any]] = field(default_factory=list)
    ui_action_results: list[Dict[str, Any]] = field(default_factory=list)
    ui_actions_executed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        now = self.completed_at or time.time()
        duration = max(0.0, now - self.started_at)
        ok = self.status == "completed" and self.exit_code == 0 and not self.timed_out and not self.cancelled
        payload = {
            "ok": ok,
            "job_id": self.job_id,
            "status": self.status,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "duration_seconds": round(duration, 3),
            "summary": self._summary(ok),
            "background": self.status == "running",
            "command": " ".join(self.command),
            "ui_actions": self.ui_actions,
            "ui_action_results": self.ui_action_results,
            "ui_actions_executed": self.ui_actions_executed,
            "ui_action_review_available": bool(self.ui_actions),
            "ui_action_summary": self._ui_action_summary(),
        }
        cards = self._ui_action_cards()
        if cards:
            payload["cards"] = cards
        if self.error:
            payload["error"] = self.error
        if self.result_payload:
            payload["runner_result"] = self.result_payload
        return payload

    def _summary(self, ok: bool) -> str:
        if self.status == "running":
            return f"Script job {self.job_id} is running"
        if self.cancelled:
            return f"Script job {self.job_id} was cancelled"
        if self.timed_out:
            return f"Script job {self.job_id} timed out after {self.timeout_seconds}s"
        if ok:
            return f"Script job {self.job_id} completed successfully"
        return f"Script job {self.job_id} failed"

    def _ui_action_summary(self) -> str:
        if not self.ui_actions:
            return ""
        total = len(self.ui_actions)
        if not self.ui_actions_executed:
            return f"{total} UI action(s) pending"
        succeeded = len([item for item in self.ui_action_results if item.get("ok")])
        failed = len(self.ui_action_results) - succeeded
        parts = [f"{succeeded} UI action(s) succeeded"]
        if failed:
            parts.append(f"{failed} failed")
        return ", ".join(parts)

    def _ui_action_cards(self) -> list[Dict[str, Any]]:
        if not self.ui_actions:
            return []
        failed_actions = [
            self.ui_actions[index]
            for index, result in enumerate(self.ui_action_results)
            if index < len(self.ui_actions) and not result.get("ok")
        ]
        card = {
            "type": "ui_action_review",
            "title": "UI Actions",
            "subtitle": self._ui_action_summary(),
            "path": self.job_id,
            "actions": [
                {
                    "id": "review_ui_actions",
                    "label": "Review UI Actions",
                    "payload": {
                        "job_id": self.job_id,
                        "ui_actions": self.ui_actions,
                        "ui_action_results": self.ui_action_results,
                    },
                }
            ],
        }
        if failed_actions:
            card["actions"].append({
                "id": "replay_failed_ui_actions",
                "label": "Replay Failed Actions",
                "payload": {
                    "job_id": self.job_id,
                    "ui_actions": failed_actions,
                },
            })
        return [card]


class ScriptJobManager:
    QUICK_TIMEOUT_SECONDS = 60
    LONG_TIMEOUT_SECONDS = 1800
    TERMINATE_GRACE_SECONDS = 3

    def __init__(self, project_root: str | os.PathLike | None = None):
        self.project_root = Path(project_root or self._default_project_root()).resolve()
        self.runner_path = self.project_root / "plugins" / "ai_assistant" / "runtime" / "script_runner.py"
        self.jobs: Dict[str, ScriptJob] = {}
        self.ui_action_executor = None

    def set_ui_action_executor(self, executor) -> None:
        self.ui_action_executor = executor

    def run_script(
        self,
        *,
        code: Optional[str] = None,
        script_path: Optional[str] = None,
        cwd: Optional[str] = None,
        db_path: Optional[str] = None,
        wells: Optional[list] = None,
        execution_mode: str = "quick",
        timeout_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        mode = self._normalize_mode(execution_mode)
        timeout = self._timeout_for_mode(mode, timeout_seconds)
        job = self._start_job(
            code=code,
            script_path=script_path,
            cwd=cwd,
            db_path=db_path,
            wells=wells,
            execution_mode=mode,
            timeout_seconds=timeout,
        )
        if mode == "background":
            return job.to_dict()
        return self._wait_for_job(job.job_id, timeout)

    def get_job(self, job_id: str) -> Dict[str, Any]:
        job = self.jobs.get(str(job_id or ""))
        if not job:
            return {"ok": False, "error": f"Script job not found: {job_id}", "job_id": job_id}
        self._refresh_job(job)
        self._execute_ui_actions_if_ready(job)
        return job.to_dict()

    def stop_job(self, job_id: str) -> Dict[str, Any]:
        job = self.jobs.get(str(job_id or ""))
        if not job:
            return {"ok": False, "error": f"Script job not found: {job_id}", "job_id": job_id}
        if job.status != "running":
            return job.to_dict()
        job.cancelled = True
        self._terminate(job)
        self._refresh_job(job)
        if job.status == "running":
            job.status = "cancelled"
            job.completed_at = time.time()
            job.exit_code = -1
        return job.to_dict()

    def _start_job(
        self,
        *,
        code: Optional[str],
        script_path: Optional[str],
        cwd: Optional[str],
        db_path: Optional[str],
        wells: Optional[list],
        execution_mode: str,
        timeout_seconds: int,
    ) -> ScriptJob:
        job_id = str(uuid.uuid4())
        payload = {
            "job_id": job_id,
            "code": code,
            "script_path": os.path.abspath(script_path) if script_path else None,
            "cwd": cwd or str(self.project_root),
            "db_path": db_path or "",
            "wells": wells or [],
            "project_root": str(self.project_root),
            "timeout_seconds": timeout_seconds,
        }
        payload_file = tempfile.NamedTemporaryFile(prefix="pylog_script_job_", suffix=".json", delete=False, mode="w", encoding="utf-8")
        try:
            json.dump(payload, payload_file, ensure_ascii=False)
            payload_path = payload_file.name
        finally:
            payload_file.close()

        command = [sys.executable, str(self.runner_path), "--payload", payload_path]
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUTF8", "1")
        process = subprocess.Popen(
            command,
            cwd=str(cwd or self.project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            env=env,
        )
        job = ScriptJob(
            job_id=job_id,
            mode=execution_mode,
            payload_path=payload_path,
            process=process,
            started_at=time.time(),
            timeout_seconds=timeout_seconds,
            command=command,
        )
        self.jobs[job_id] = job
        return job

    def _wait_for_job(self, job_id: str, timeout_seconds: int) -> Dict[str, Any]:
        job = self.jobs[job_id]
        try:
            stdout, stderr = job.process.communicate(timeout=timeout_seconds)
            self._finish_job(job, stdout, stderr, job.process.returncode)
        except subprocess.TimeoutExpired:
            job.timed_out = True
            self._terminate(job)
            stdout, stderr = job.process.communicate()
            self._finish_job(job, stdout, stderr, -1)
        self._execute_ui_actions_if_ready(job)
        return job.to_dict()

    def _refresh_job(self, job: ScriptJob) -> None:
        if job.status != "running":
            return
        if time.time() - job.started_at > job.timeout_seconds:
            job.timed_out = True
            self._terminate(job)
            stdout, stderr = job.process.communicate()
            self._finish_job(job, stdout, stderr, -1)
            return
        if job.process.poll() is None:
            return
        stdout, stderr = job.process.communicate()
        self._finish_job(job, stdout, stderr, job.process.returncode)
        self._execute_ui_actions_if_ready(job)

    def _finish_job(self, job: ScriptJob, stdout: str, stderr: str, exit_code: Optional[int]) -> None:
        runner_payload, cleaned_stdout = self._extract_runner_payload(stdout or "")
        job.stdout = cleaned_stdout
        job.stderr = stderr or ""
        job.exit_code = exit_code
        job.completed_at = time.time()
        job.result_payload = runner_payload or {}
        if runner_payload:
            job.stdout = runner_payload.get("stdout", job.stdout) or ""
            job.stderr = "\n".join(part for part in [runner_payload.get("stderr"), job.stderr] if part) or ""
            job.exit_code = runner_payload.get("exit_code", job.exit_code)
            job.error = runner_payload.get("error")
            job.ui_actions = self._normalize_ui_actions(runner_payload.get("ui_actions"))
        if job.cancelled:
            job.status = "cancelled"
        elif job.timed_out:
            job.status = "timed_out"
            job.error = job.error or "timeout"
        elif job.exit_code == 0 and not job.error:
            job.status = "completed"
        else:
            job.status = "failed"
            job.error = job.error or job.stderr or f"Script exited with code {job.exit_code}"

    def _execute_ui_actions_if_ready(self, job: ScriptJob) -> None:
        if job.status == "running" or job.ui_actions_executed or not job.ui_actions:
            return
        job.ui_actions_executed = True
        if job.status != "completed":
            job.ui_action_results = [
                {
                    "ok": False,
                    "type": action.get("type") if isinstance(action, dict) else "invalid",
                    "error": f"Skipped UI action because script job status is {job.status}",
                }
                for action in job.ui_actions
            ]
            return

        executor = self.ui_action_executor
        if executor is None:
            job.ui_action_results = [
                {
                    "ok": False,
                    "type": action.get("type") if isinstance(action, dict) else "invalid",
                    "error": "UI action executor is unavailable",
                }
                for action in job.ui_actions
            ]
            return
        try:
            job.ui_action_results = executor.execute_many(job.ui_actions)
        except Exception as exc:
            job.ui_action_results = [{"ok": False, "type": "ui_actions", "error": str(exc)}]

    @staticmethod
    def _normalize_ui_actions(actions: Any) -> list[Dict[str, Any]]:
        if not isinstance(actions, list):
            return []
        normalized = []
        for action in actions:
            if isinstance(action, dict):
                normalized.append(action)
            else:
                normalized.append({"type": "invalid", "value": str(action)})
        return normalized

    def _terminate(self, job: ScriptJob) -> None:
        if job.process.poll() is not None:
            return
        try:
            job.process.terminate()
            job.process.wait(timeout=self.TERMINATE_GRACE_SECONDS)
        except Exception:
            try:
                job.process.kill()
            except Exception:
                pass

    @staticmethod
    def _extract_runner_payload(stdout: str) -> tuple[Dict[str, Any], str]:
        lines = stdout.splitlines()
        payload = {}
        kept = []
        for line in lines:
            if line.startswith(RESULT_MARKER):
                try:
                    payload = json.loads(line[len(RESULT_MARKER):])
                except Exception:
                    payload = {}
            else:
                kept.append(line)
        cleaned = "\n".join(kept)
        if stdout.endswith("\n") and cleaned:
            cleaned += "\n"
        return payload, cleaned

    @classmethod
    def _normalize_mode(cls, mode: Optional[str]) -> str:
        normalized = str(mode or "quick").strip().lower()
        if normalized in {"quick", "background", "long"}:
            return normalized
        return "quick"

    @classmethod
    def _timeout_for_mode(cls, mode: str, timeout_seconds: Optional[int]) -> int:
        if timeout_seconds:
            try:
                value = int(timeout_seconds)
                if value > 0:
                    return value
            except Exception:
                pass
        return cls.LONG_TIMEOUT_SECONDS if mode == "long" else cls.QUICK_TIMEOUT_SECONDS

    @staticmethod
    def _default_project_root() -> Path:
        return Path(__file__).resolve().parents[3]


_GLOBAL_MANAGER: Optional[ScriptJobManager] = None


def get_script_job_manager(project_root: str | os.PathLike | None = None) -> ScriptJobManager:
    global _GLOBAL_MANAGER
    if _GLOBAL_MANAGER is None:
        _GLOBAL_MANAGER = ScriptJobManager(project_root=project_root)
    return _GLOBAL_MANAGER
