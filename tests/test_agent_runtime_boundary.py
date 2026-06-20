from __future__ import annotations

import os
import sys
import unittest

from PySide6.QtCore import QObject, Signal


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from plugins.ai_assistant.ai_core.agent_runtime import AgentRuntime
from plugins.ai_assistant.ai_core.events import AgentEvent, AgentEventType


class DummyWorker(QObject):
    finished = Signal(str)
    reasoning_update = Signal(str)
    content_update = Signal(str)
    error = Signal(str)
    stopped = Signal()
    system_message = Signal(str)
    tool_call_started = Signal(str, dict)
    tool_call_finished = Signal(str, str, str)
    round_finished = Signal()
    task_progress = Signal(dict)

    def __init__(self):
        super().__init__()
        self.run_called = False
        self.stop_called = False

    async def run_async(self):
        self.run_called = True
        self.content_update.emit("hello")
        self.tool_call_started.emit("tool_demo", {"x": 1})
        self.tool_call_finished.emit("tool_demo", "success", '{"ok": true}')
        self.task_progress.emit({"phase": "demo"})
        self.finished.emit("done")
        return "worker-result"

    def stop(self):
        self.stop_called = True
        self.stopped.emit()

    def get_tool_inventory_payload(self):
        return {
            "summary": {"total": 1, "by_source": {"local": 1}},
            "tools": [{"name": "tool_demo", "source": "local"}],
        }


class AgentEventTests(unittest.TestCase):
    def test_tool_started_event_uses_stable_shape(self):
        event = AgentEvent.tool_started("tool_demo", {"x": 1})

        self.assertEqual(event.type, AgentEventType.TOOL_STARTED)
        self.assertEqual(event.tool_name, "tool_demo")
        self.assertEqual(event.payload["args"], {"x": 1})

    def test_message_and_reasoning_events_keep_content(self):
        self.assertEqual(AgentEvent.message_delta("visible").content, "visible")
        self.assertEqual(AgentEvent.reasoning_delta("thinking").content, "thinking")


class AgentRuntimeBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_delegates_run_and_reemits_worker_signals_as_events(self):
        worker = DummyWorker()
        runtime = AgentRuntime(worker)
        events = []
        visible = []
        finished = []

        runtime.event.connect(events.append)
        runtime.content_update.connect(visible.append)
        runtime.finished.connect(finished.append)

        result = await runtime.run_async()

        self.assertEqual(result, "worker-result")
        self.assertTrue(worker.run_called)
        self.assertEqual(visible, ["hello"])
        self.assertEqual(finished, ["done"])
        self.assertEqual(
            [event.type for event in events],
            [
                AgentEventType.MESSAGE_DELTA,
                AgentEventType.TOOL_STARTED,
                AgentEventType.TOOL_FINISHED,
                AgentEventType.TASK_PROGRESS,
                AgentEventType.FINISHED,
            ],
        )

    async def test_runtime_stop_delegates_to_worker_and_emits_stopped_event(self):
        worker = DummyWorker()
        runtime = AgentRuntime(worker)
        events = []
        stopped = []

        runtime.event.connect(events.append)
        runtime.stopped.connect(lambda: stopped.append(True))

        runtime.stop()

        self.assertTrue(worker.stop_called)
        self.assertEqual(stopped, [True])
        self.assertEqual(events[-1].type, AgentEventType.STOPPED)

    async def test_runtime_delegates_tool_inventory_payload(self):
        worker = DummyWorker()
        runtime = AgentRuntime(worker)

        payload = runtime.get_tool_inventory_payload()

        self.assertEqual(payload["summary"]["total"], 1)
        self.assertEqual(payload["tools"][0]["name"], "tool_demo")


if __name__ == "__main__":
    unittest.main()
