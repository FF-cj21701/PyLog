# Codex CLI Design Migration Plan for PyLog

2026-06-27

## 1. Purpose

This document defines how PyLog will migrate selected Codex CLI design patterns and local agent capabilities into the native PyLog AI Assistant.

The goal is not to embed, wrap, fork, or keep Codex CLI as a fallback backend. The goal is to evolve PyLog's own `plugins/ai_assistant` runtime into a local, extensible, domain-aware agent system inspired by Codex CLI's architecture.

## 2. Final Target

PyLog should own a native local agent runtime with these capabilities:

```text
PyLog Native Agent Runtime
+-- Agent Loop
+-- Tool Manager
+-- Context Manager
+-- File Editor
+-- Shell Executor
+-- Workspace Page Host
+-- Execution Policy
+-- Skill System
+-- Verification Loop
```

Codex CLI is used only as an architectural reference during design review. It must not become a required runtime dependency, optional backend, user-facing mode, or long-term compatibility target.

## 3. Current Project Fit

PyLog already has many useful foundations:

- `AsyncAIWorker` already contains a streaming ReAct-style loop.
- `ToolDispatcher`, `ToolSpec`, and `ToolResult` already provide a tool protocol.
- `ExecutionPolicy` already enforces read-before-write and verification-before-finish behavior.
- `.agents/skills` already follows a skill-oriented layout that can be reused by the native PyLog agent.
- `pylog_mcp_server.py` already exposes useful domain APIs such as well discovery, curve sampling, curve analysis, and plotting.
- `ChatService` already centralizes UI-to-agent orchestration.

The migration should therefore be a refactor and hardening project, not a rewrite.

## 4. Non-Goals

The implementation must not:

- Add Codex CLI as a PyLog backend.
- Depend on `codex.exe`, `codex exec`, `codex mcp-server`, or `openai-codex`.
- Fork `openai/codex`.
- Move PyLog domain behavior into Codex-specific plugins.
- Make Codex configuration files part of the normal PyLog runtime path.
- Replace PyLog's current OpenAI-compatible model configuration.

## 5. Target Architecture

### 5.1 Runtime Layer

Introduce a native runtime boundary:

```text
ChatService
+-- AgentRuntime
    +-- ModelClient
    +-- ContextManager
    +-- ToolManager
    +-- WorkspacePageHost
    +-- ExecutionPolicy
    +-- VerificationCoordinator
    +-- AgentEventEmitter
```

Responsibilities:

- `ChatService` owns UI lifecycle, cancellation, and signal wiring.
- `AgentRuntime` owns the full agent loop.
- `ModelClient` owns provider calls and streaming.
- `ContextManager` builds prompt context from PyLog state.
- `ToolManager` owns tool discovery, ranking, routing, and execution.
- `WorkspacePageHost` owns reusable local HTML workspace pages for review, reports, plans, and structured agent output.
- `ExecutionPolicy` owns safety gates.
- `VerificationCoordinator` owns post-change verification requirements.
- `AgentEventEmitter` converts runtime events into UI-friendly payloads.

### 5.2 Agent Loop

Extract the current loop from `AsyncAIWorker._run_react_loop` into a dedicated runtime component.

The loop should follow this lifecycle:

```text
build context
→ request model response
→ stream reasoning/content
→ collect tool calls
→ execute tools through ToolManager
→ record observations in AgentState
→ enforce verification/finish policy
→ continue or finish
```

The loop must remain provider-neutral and continue to support OpenAI-compatible chat endpoints.

### 5.3 Tool Manager

Upgrade `ToolDispatcher` into a fuller `ToolManager`.

Required capabilities:

- Discover local tools from `plugins/ai_assistant/tools`.
- Load optional MCP tools.
- Normalize all tools into `ToolSpec`.
- Normalize all outputs into `ToolResult`.
- Route tools by task type, domain tags, capability tags, and current state.
- Apply policy before and after every tool call.
- Emit structured tool events for the UI.

Tool classes should continue to use the existing `BaseTool` contract.

### 5.4 File Editor

Make patch-first editing the primary file modification path.

Required behavior:

- Existing files must be read before modification.
- Patch tools should prefer exact old/new hunks over full-file overwrite.
- Patch failures must return actionable errors.
- File changes must be recorded in `AgentState`.
- Python/script changes must trigger verification guidance.
- Full overwrite tools should remain available only for file creation or explicitly allowed cases.

The existing `tool_apply_patch` should become the canonical editor path.

### 5.5 Shell Executor

Replace the current simple shell tool with a controlled shell executor.

Required behavior:

- Default working directory is the PyLog project root.
- Commands run with timeout.
- Commands run without `shell=True` unless explicitly required and approved.
- Dangerous commands are blocked or require approval.
- Output is captured as stdout, stderr, exit code, and summary.
- Long output is truncated for UI display while preserving enough detail for debugging.
- Verification commands are classified separately from arbitrary shell commands.

Default blocked command categories:

- recursive delete
- `git reset --hard`
- forced checkout/revert
- disk/system mutation outside the project
- package installation without explicit user approval
- background processes without a controlled lifecycle

### 5.6 Context Manager

Introduce a structured `ContextManager` so the model receives high-signal PyLog context instead of raw prompt concatenation.

Context sources:

- current selected well
- selected curves
- database path
- plot/window state
- active script editor state
- recent tool observations
- enabled skills
- conversation summary
- user message

Context priority:

1. Current user selection and task text.
2. Well, curve, and database metadata.
3. Active script/editor state.
4. Relevant skills.
5. Recent tool results.
6. Older conversation summary.

The context manager should enforce a token or character budget and prefer structured summaries over large raw data payloads.

### 5.7 Skill System

Keep `.agents/skills` as the single source of truth for domain skills.

Required behavior:

- `SkillService` remains the discovery layer.
- Skills keep using `SKILL.md`.
- Skill metadata should inform tool routing and context selection.
- Petrophysics and PyLog scripting tasks should consult the relevant skill before generating formulas or scripts.
- Skills should remain model-provider-neutral and not mention Codex-specific runtime assumptions unless absolutely necessary.

### 5.8 Execution Policy and Verification

Continue strengthening the existing `ExecutionPolicy`.

Required rules:

- Read before write.
- High-risk tools must be blocked or require approval.
- Destructive tools must be blocked by default.
- Modified files require verification before finish.
- Verification failures must prevent normal completion unless the assistant clearly reports the unresolved failure.
- `tool_finish` remains a control signal and should not duplicate the visible final answer.

Verification should be selected by target:

- user script: syntax/import check, optional script execution
- project source: targeted tests or import checks
- UI/resource changes: lightweight regression checks
- data workflow: sample-based validation and summary statistics

### 5.9 Workspace Page Host

Introduce a reusable local page-host layer so the agent can open structured workspace pages instead of forcing every rich UI flow into chat bubbles or one-off Qt dialogs.

Required behavior:

- Open local HTML-backed pages in either dialog or MDI mode.
- Reuse an existing page when the same stable `page_id` is requested again.
- Support Python-to-JS payload updates through a shared bridge contract.
- Support JS-to-Python action callbacks for page-local actions such as accept, reject, close, or refresh.
- Keep page templates local to PyLog and provider-neutral.
- Allow specialized pages such as script review to coexist with a generic agent content page.

Recommended first consumers:

- script review pages
- task/report pages
- agent-generated summaries and structured guidance
- future skill-specific inspector or explanation pages

## 6. Implementation Phases

### Phase 1: Runtime Boundary

Deliverables:

- Add `AgentRuntime` as the main loop owner.
- Move loop logic out of `AsyncAIWorker` without changing behavior.
- Keep `ChatService` public behavior unchanged.
- Add runtime event objects for message, tool, policy, verification, and finish events.

Acceptance criteria:

- Existing AI chat still works.
- Existing tests for agent core behavior still pass.
- No Codex CLI dependency is introduced.

### Phase 2: Tool Manager Hardening

Deliverables:

- Convert `ToolDispatcher` into or wrap it with `ToolManager`.
- Keep all existing tools compatible.
- Add state-aware tool ranking and filtering.
- Ensure every tool execution passes through policy and result normalization.
- Add a small reusable agent-page tool surface for opening, updating, and closing structured workspace pages.

Acceptance criteria:

- Local tools and MCP tools execute through the same path.
- Tool metadata is visible to routing and policy.
- Tool errors produce normalized `ToolResult` payloads.
- Agent-owned page tools can open or update a stable workspace page without creating duplicate tabs for the same `page_id`.

### Phase 3: Patch-First File Editor

Deliverables:

- Promote `tool_apply_patch` as the default edit tool.
- Limit overwrite-style tools to creation or explicitly approved cases.
- Improve patch errors and file-change event reporting.

Acceptance criteria:

- Existing-file edits require a prior read.
- Patch failures do not partially corrupt files.
- Modified files are tracked in `AgentState`.

### Phase 4: Controlled Shell Executor

Deliverables:

- Replace the simple `shell=True` terminal implementation with a policy-aware executor.
- Add command classification.
- Add deny/approval rules.
- Add verification-command helpers.

Acceptance criteria:

- Safe read-only commands run normally.
- Dangerous commands are blocked by default.
- Test/import/verification commands return structured results.

### Phase 5: Structured Context Manager

Deliverables:

- Add a `ContextManager`.
- Move `ChatService.build_context_block` logic into it.
- Add structured well, curve, database, plot, script, skill, and history context sections.

Acceptance criteria:

- Current UI selections still appear in prompts.
- Large data is summarized rather than dumped.
- Domain tasks receive relevant skills and API constraints.

### Phase 6: Skill-Driven Domain Behavior

Deliverables:

- Use skill metadata for task routing.
- Require `pylog-scripting` for script-generation tasks.
- Require `petropy` for petrophysical calculations.
- Make skill loading visible in tool progress.

Acceptance criteria:

- Domain calculations consult the relevant skill before producing formulas.
- Generated scripts follow PyLog API conventions.
- Disabled skills are respected.

### Phase 7: Verification Loop Completion

Deliverables:

- Strengthen finish blocking after mutations.
- Improve automatic verification recommendations.
- Add clear unresolved-failure reporting.

Acceptance criteria:

- Agent cannot finish silently after modifying files without verification.
- Verification success clears the finish blocker.
- Verification failure leads to repair attempts or an explicit unresolved report.

## 7. Suggested File-Level Landing Zones

Primary areas:

- `plugins/ai_assistant/ai_core/agent_runtime.py`
- `plugins/ai_assistant/ai_core/context_manager.py`
- `plugins/ai_assistant/ai_core/tool_manager.py`
- `plugins/ai_assistant/ai_core/shell_executor.py`
- `plugins/ai_assistant/ai_core/events.py`

Existing files to refactor carefully:

- `plugins/ai_assistant/ai_core/api_client.py`
- `plugins/ai_assistant/services/chat_service.py`
- `plugins/ai_assistant/ai_core/tool_dispatcher.py`
- `plugins/ai_assistant/ai_core/policy.py`
- `plugins/ai_assistant/tools/os_tool.py`
- `plugins/ai_assistant/tools/patch_tool.py`

UI/workspace page surfaces:

- `plugins/ai_assistant/ui/widgets/agent_page_host.py`
- `plugins/ai_assistant/ui/resources/review_template.html`
- `plugins/ai_assistant/ui/resources/agent_page_template.html`
- `plugins/ai_assistant/tools/agent_page_tool.py`

Tests should be added under `tests/` and should avoid requiring live model calls.

## 8. Testing Strategy

Unit tests:

- runtime loop state transitions
- context manager priority and truncation
- tool routing and result normalization
- read-before-write enforcement
- patch failure behavior
- shell command classification
- finish blocking after file modification
- skill selection for domain tasks

Integration tests:

- local tool execution through `ToolManager`
- MCP tool discovery through the existing PyLog MCP server
- script generation workflow with `pylog-scripting`
- petrophysical calculation workflow with `petropy`
- file edit plus verification workflow

Regression tests:

- existing chat behavior
- settings/profile persistence
- current tool specs
- current task plan UI events
- current verification tools
- agent page template structure and page-host wiring

No test should require Codex CLI.

## 9. Success Criteria

The migration is complete when PyLog's native agent can:

- plan and execute multi-step local tasks;
- use domain-aware context from wells, curves, plots, scripts, and databases;
- select and run local/MCP/PyLog tools through one manager;
- modify files using patch-first editing;
- run shell commands through a controlled executor;
- enforce read-before-write and verification-before-finish;
- consult `.agents/skills` for domain workflows;
- show structured progress and tool events in the UI;
- open reusable structured workspace pages for review and reporting;
- remain independent from Codex CLI installation or availability.

## 10. Guiding Principle

Migrate the architecture, not the dependency.

PyLog should absorb the useful Codex CLI ideas: local agent loop, disciplined tool execution, patch-first editing, sandbox-like policy boundaries, progressive context, skills, and verification. PyLog should not become a wrapper around Codex CLI.
