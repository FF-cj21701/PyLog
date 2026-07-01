## Notes / 说明

- This changelog now uses bilingual titles and English body text for long-term encoding stability.
- Some older entries were historically affected by mojibake. Those sections were normalized into readable English summaries while preserving dates and main themes.

## [2026-07-01] - Plot / Window State Context Section / 绘图窗口状态上下文段

- Added a structured Plot / Window State context section:
  - supports explicit `plot_window_state`, `plot_state`, `window_state`, and nested `plot_window_state` payloads
  - formats active window title/type, plot title, well, database path, depth range, selected curves, track counts, and track summaries
  - places plot/window state after active script state and before task-plan/runtime summaries
- Added `WorkspaceStateCollector` and wired `ChatService` to inject the active MDI plot/data-viewer state automatically before each prompt.
- Data Viewer context now includes curve names, depth range, table row/column counts, and visible columns through the same Plot / Window State section.
- Marked Skills Summary as deferred because the current skill catalog is still provisional; it should move into ContextManager after skill metadata/routing stabilizes.
- Added regression coverage for plot/window formatting, nested payload extraction, active workspace injection, data-viewer summaries, section ordering, and policy priority.

## [2026-06-30] - Non-opening Script Edit Draft Flow / 非自动打开脚本编辑草稿流程

- Replaced the old `try_preview_change(...)` helper with `draft_change_in_open_editor(...)`.
- File editing tools now only send draft/review updates when the target Python script is already open in an editor.
- `tool_edit_file`, `tool_overwrite_file`, and `tool_insert_into_file` no longer open script editors implicitly when editing `.py` files.
- `tool_append_file` no longer reopens Python scripts after appending content.
- Added a structured Recent Tool Results context section:
  - supports single tool-result items, batched recent result lists, and `AgentState.tool_steps`-style payloads
  - preserves high-signal fields such as status, summary, error, path, exit code, preview state, and script draft state
  - limits context size while keeping failed tool results visible for follow-up repair
- Wired recent runtime state into chat prompt composition:
  - `ChatService` now merges `agent_state.tool_steps` into context before each new prompt
  - latest verification results are also injected so the next turn can repair failed checks
  - user-selected well/curve/script context is preserved without mutating the original context payload
- Added section-level context budgeting policies:
  - centralizes section priority and line/item budgets in `ContextManager.SECTION_POLICIES`
  - keeps selection and active script state ahead of lower-priority runtime summaries
  - emits explicit `omitted` and `truncated` hints when recent tool results are compressed
- Added a structured Task Plan context section:
  - formats task-plan domain, source, current step id, step status, titles, and notes
  - marks the current step inline so follow-up turns can continue from the right place
  - injects `AgentState.current_plan` from `ChatService` before recent tool results
- Added a structured Retrieved Context section:
  - supports explicit `retrieved_context`, `search_result`, `file_summary`, and `code_location` items
  - extracts code/file locations from search-style tool results such as `tool_search_code`
  - ranks retrieved items by score and location specificity, then emits omitted hints when compressed
- Added regression coverage for:
  - structured draft payloads for already-open script editors
  - no draft signal emission when the target script is not open
  - insert-tool script-state propagation through the renamed draft helper
  - recent tool-result extraction, ordering, truncation, and failure retention
  - automatic runtime context injection from `ChatService`
  - context section priority and budget behavior
  - task-plan formatting, ordering, budget truncation, and prompt injection
  - retrieved-context formatting, search-result extraction, ordering, and budget truncation

## [2026-06-29] - Context Manager Boundary Foundation / 上下文管理器边界基础

- Started Phase 5 of the Codex-style native agent migration by introducing a dedicated context-building boundary.
- Added `plugins/ai_assistant/ai_core/context_manager.py` with:
  - `ContextManager` for prompt context block construction
  - `ContextSection` as the first structured context section model
  - existing `[ALIVE Context]` well / curve formatting preserved for compatibility
  - curve-to-well name lookup retained through the selected database path
- Routed `ChatService.compose_prompt(...)` and `ChatService.build_context_block(...)` through `ContextManager`.
- Added regression coverage for:
  - empty context behavior
  - existing well context formatting
  - curve context database well-name lookup
  - ChatService prompt composition delegation
- Extended the first structured context section pass with Active Script State:
  - supports direct `active_script` / `script_state` context items
  - also extracts `script_state` from tool result payloads
  - includes editor id, script path, unsaved-change state, AI draft/review state, review session id, hashes, and run/save targets
  - keeps selection context before script-state context for prompt stability
- Current verification command:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_ai_agent_core_behaviors.py tests\test_agent_runtime_boundary.py tests\test_chat_ui_template_regressions.py -q`
- Current result:
  - `206 passed`

## [2026-06-29] - Controlled Shell Executor Foundation / 受控 Shell 执行器基础

- Started Phase 4 of the Codex-style native agent migration by introducing a policy-aware shell execution boundary.
- Added `plugins/ai_assistant/ai_core/shell_executor.py` with:
  - normalized command results including `stdout`, `stderr`, `exit_code`, `cwd`, timeout state, blocked state, and verification classification
  - default project-root working directory behavior
  - timeout handling and output truncation
  - shell-control blocking for commands that would require `shell=True`
  - default blocking for destructive commands such as `git reset --hard`, forced checkout/restore/clean/revert, recursive delete patterns, and package installation commands
- Reworked `tool_run_shell_command` to use the controlled executor instead of direct `subprocess.run(..., shell=True)`.
- Routed verification helper command execution through the same controlled executor while leaving detached background plot execution unchanged.
- Added regression coverage for:
  - safe command execution without shell mode
  - verification-command classification
  - shell-control operator blocking
  - destructive Git command blocking through the public terminal tool
- Current verification command:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_ai_tool_specs.py::ToolSpecConsistencyTests tests\test_ai_tool_specs.py::RunPythonFileBehaviorTests -q`
- Current result:
  - `16 passed`

## [2026-06-29] - Review Card Flow, Registry-backed Review Pages & Theme Alignment / 审查卡片流程、注册表审查页与主题对齐

- Follow-up refinement pass on top of the 2026-06-28 review-page foundation, focused on making the saved-review path the default user-facing flow.
- Refined the post-edit review flow so chat cards now behave like end-of-reply change summaries instead of mid-tool inline status artifacts:
  - file-change cards are accumulated during tool execution
  - cards are only published after the assistant reply is finalized
  - repeated edits to the same file in one reply continue to merge their diff stats and actions
- Reworked review-card wording and structure for a cleaner workspace-style UI:
  - card titles now use `Edited <filename>`
  - the action button now uses `Review`
  - the card group header now uses `File changed in this reply` / `Files changed in this reply (N)`
- Fixed the chat-card action bridge so review-card clicks can reliably reach Python:
  - exposed the chat `pyBridge` on `window.pyBridge`
  - changed card-action payload transport to URL-safe JSON encoding / decoding
- Added a reusable document-opening layer for local workspace files:
  - introduced `tool_open_html_preview` to open `.html` / `.htm` files as rendered web previews inside PyLog
  - introduced `tool_open_document` as a central router that reuses existing openers and currently dispatches `.py` files to the script editor and `.html` / `.htm` files to the HTML preview surface
  - extended `ToolExecutor` with a dedicated HTML preview signal / slot so future document types can plug into the same routing model without duplicating window-management logic
- Formalized tool metadata extensibility for discovery-oriented fields:
  - added first-class `keywords` support to the `BaseTool -> ToolSpec -> ToolManager inventory` pipeline
  - updated page/document opening tools to include retrieval-friendly keyword sets such as `html`, `web page`, `html preview`, `open document`, and `script editor`
  - documented the metadata evolution pattern in `docs/TOOLS_METADATA_GUIDE.md` so future fields like `aliases`, `examples`, and `ui_surface` can be added consistently
  - connected `keywords` to actual tool retrieval behavior:
    - `TaskDomainRouter` now keeps keyword-matched tools visible even when coarse domain tags would otherwise filter them out
    - `ToolSelectionStrategy` now uses keyword relevance as a same-bucket ranking signal so prompt-matched tools appear earlier in the model-visible tool list
  - expanded retrieval keywords across high-frequency tool groups:
    - code search and navigation tools such as `tool_search_code`, `tool_find_files`, `tool_find_symbol`, and `tool_find_references`
    - file editing tools such as `tool_edit_file`, `tool_overwrite_file`, `tool_insert_into_file`, and `tool_apply_patch`
    - verification tools such as `tool_verify_target`, `tool_run_python_file`, `tool_run_test_command`, `tool_run_lint_command`, `tool_run_format_command`, and `tool_run_import_check`
    - command / shell entry tools such as `tool_run_shell_command`
    - core PyLog data and plotting tools such as `list_wells`, `list_curves`, `plot`, `create_plot`, `update_plot`, and plot-style / plot-inspection operations
  - expanded retrieval keywords across second-tier workflow tools:
    - file reading and inspection tools such as `tool_read_file`, `tool_search_in_file`, and directory/file inspection helpers
    - script-editor lifecycle tools such as `tool_open_script`, `tool_write_script_file`, `tool_set_script_code`, `tool_run_script`, `tool_save_script`, and `tool_get_script_state`
    - planning tools such as `tool_create_task_plan`, `tool_get_task_plan`, and `tool_update_task_plan`
    - documentation/help lookup via `tool_get_help`
  - fixed chat metadata popovers for HTML-backed file pills so preview content is rendered as escaped text instead of live DOM, preventing local HTML snippets from altering the AI chat surface when metadata dialogs are opened
  - added regression coverage for the shared bridge path
- Removed the requirement that a script editor window must remain open before a review page can be opened from chat:
  - introduced `plugins/ai_assistant/ui/review_registry.py`
  - review records are now registered globally when AI-authored script changes are persisted
  - chat-card `Review` now opens the saved review page directly from that registry
  - the chat-side review path no longer falls back to locating an open script editor
- Continued the review-surface English cleanup:
  - script-editor toolbar action now uses `Review`
  - the review workspace page uses `AI Review`
  - review-card copy and fallback labels were normalized into English
- Reworked the review page visual surface so it feels like an editor-adjacent workspace tab instead of a nested showcase panel:
  - removed the extra inner review-shell "window" look
  - simplified the top section to a path-first layout
  - reshaped `Diff / Original / Draft` into a flatter tab-strip style
  - tightened code spacing and flattened the content panel
- Fixed review-page theme alignment so it now follows the shared ThemeManager-driven web theme injection path correctly:
  - moved `dynamic-theme-vars` after the static fallback style block so injected CSS variables override defaults
  - reduced dependence on hard-coded dark presentation choices
  - confirmed that the review page now consumes the same web theme variable layer used by other agent/editor web surfaces
- Removed obsolete review footer copy from the page:
  - hid the footer section
  - cleared the static footer default text
  - stopped repopulating that note at render time
- Added or updated regression coverage for:
  - deferred file-change card publication
  - card action bridge payload transport
  - registry-backed review opening without an open script editor
  - review-template structure, footer removal, and dynamic-theme override ordering
- Current verification commands:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_ai_agent_core_behaviors.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_chat_ui_template_regressions.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_ai_tool_specs.py -q`
- Current results:
  - `51 passed`
  - `25 passed`
  - `101 passed`

## [2026-06-28] - Agent Review Pages & Reusable Workspace Page Host / Agent 审查页与可复用工作区页面宿主

- Foundation pass that introduced the review-page architecture and reusable workspace HTML host before later UX tightening and registry-backed direct-open behavior.
- Reworked the AI script-change review flow away from mid-stream preview popups and toward a quieter draft-review model:
  - AI edits now apply the draft directly to the script editor workspace
  - the editor keeps explicit review-session state for original content, current draft, and diff text
  - users review those changes afterward instead of stepping through intrusive inline preview UI
- Simplified the web editor preview surface in `editor_template.html`:
  - removed the floating preview panel and its `Original / Diff / Draft` toggle UI
  - kept compatibility preview APIs so tool entry points can still activate review sessions without changing their call shape
  - preserved draft-aware editor execution and save semantics
- Added a dedicated review-page template and moved review into the workspace itself:
  - introduced `plugins/ai_assistant/ui/resources/review_template.html`
  - changed script review to open as an MDI workspace page instead of a transient dialog
  - accept / reject actions now resolve the review session and close the review page when appropriate
- Added a reusable local HTML page-host layer for future agent UI surfaces:
  - introduced `plugins/ai_assistant/ui/widgets/agent_page_host.py`
  - added `AgentPageBridge`, shared host logic, `AgentPageDialog`, and `AgentPageWidget`
  - added `open_agent_page(...)` with both `dialog` and `mdi` modes
  - added page lookup / reuse behavior by stable `page_id`
  - added helper support for closing previously opened agent-owned workspace pages
- Added a generic agent content-page template for structured non-review surfaces:
  - introduced `plugins/ai_assistant/ui/resources/agent_page_template.html`
  - supports injected title, summary, content, meta pills, and optional structured sections
  - gives future agent pages a stable default visual surface without needing custom Qt dialogs per feature
- Added a generic agent page tool surface so the model can open, update, and close workspace pages directly:
  - introduced `tool_open_agent_page`
  - introduced `tool_update_agent_page`
  - introduced `tool_close_agent_page`
  - connected those tools through new `ToolExecutor` signals and page-host execution handlers
- Expanded regression coverage for:
  - silent review-session editor behavior
  - review-template and generic-agent-page-template structure
  - agent page host dialog / MDI support
  - executor signal wiring for generic page operations
  - tool-spec registration and required-argument rules for agent page tools
- Current verification commands:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_ai_tool_specs.py tests\test_chat_ui_template_regressions.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_file_editor_boundary.py tests\test_ai_agent_core_behaviors.py tests\test_agent_runtime_boundary.py tests\test_chat_ui_template_regressions.py -q`
- Current results:
  - `123 passed`
  - `80 passed`

## [2026-06-27] - Native Agent Runtime Migration Foundation / 原生 Agent 运行时迁移基础

- Added `docs/CODEX_DESIGN_MIGRATION_PLAN.md` to define the native PyLog agent migration plan:
  - migrate Codex-style workflow and design patterns into PyLog
  - avoid keeping Codex CLI as a runtime dependency, reference backend, or optional backend
  - organize the migration into runtime, tool management, file editing, shell execution, context, skills, and verification phases
- Completed the first runtime-boundary slice:
  - added provider-neutral `AgentEvent` / `AgentEventType`
  - added `AgentRuntime` as a thin boundary around the current async worker
  - preserved existing PySide signals while also emitting structured runtime events
  - routed `ChatService` through `AgentRuntime` without changing user-facing behavior
- Improved task-planning foundations for the migration:
  - added `plan_domain` to task progress payloads
  - made fallback plans domain-aware for coding and PyLog/geoscience scripting tasks
  - kept fallback plans hidden from the UI until a model-authored plan is accepted
- Completed the Tool Manager hardening phase:
  - added `ToolManager` as the stable boundary for tool inventory, registration, selection, routing, and execution
  - moved worker tool-config generation and execution calls through `ToolManager`
  - preserved the previous dispatcher-compatible surface for safer incremental migration
  - added registration, duplicate replacement, removal, source-based replacement, domain filtering, and capability filtering
  - changed per-turn tool assembly so MCP tools refresh by `source=mcp` instead of accumulating across turns
  - exposed tool inventory payloads through worker, runtime, and chat-service layers for future UI, diagnostics, context compression, and policy work
- Reduced perceived chat-send latency in the AI conversation UI:
  - `chat_input.js` now optimistically renders normal user messages before the Python round trip
  - `main_window.py` now skips duplicate Python-side rendering when the front end already rendered the user bubble
  - plan-control messages remain excluded from optimistic rendering to avoid special-action duplication
- Added regression coverage for:
  - runtime event shape and signal passthrough
  - runtime stop delegation
  - tool manager execution, inventory, registration, source replacement, and tag filtering
  - optimistic user-message rendering in the split chat UI resources
- Current verification command:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_ai_agent_core_behaviors.py tests\test_agent_runtime_boundary.py tests\test_chat_ui_template_regressions.py -q`
- Current result:
  - `68 passed`

## [2026-06-22] - Plot Spec Service & Template Open Dialog Fix / Plot Spec 服务与模板打开卡顿修复

- Added `scripts/services/plot_spec_service.py` as the dedicated plot-spec service layer for standardized plot construction and plot mutation.
- Clarified the intended role of the plot-spec layer:
  - normalize plot creation inputs from different entry points
  - define a shared spec structure for plot, track, and curve state
  - provide one common plot-building path through `open_plot_from_spec(...)`
  - provide one common runtime update path through `update_plot_from_commands(...)`
- Moved the architecture toward a cleaner separation of responsibilities:
  - template files are now treated primarily as serialized plot parameters/state
  - `TemplateManager` resolves saved template identity into current database curve references
  - the plot-spec service is responsible for turning resolved state into live plot widgets
  - manual plotting, template plotting, and AI/API plotting now share the same lower-level plot construction service instead of each maintaining separate widget-building logic
- Documented the real cause of the long-running "template apply becomes laggy" issue:
  - the lag was not caused by template curve settings replay
  - the lag was not caused by template track settings replay
  - the lag was not caused by template depth-track restoration
  - the lag was not caused by the shared plotting API itself
  - the actual trigger was the native `QFileDialog.getOpenFileName(...)` path used by `Open Template...`
- Confirmed the diagnosis through controlled comparisons:
  - debug plotting through the shared API remained smooth
  - direct template resolution without the native file dialog remained smooth
  - only the normal `Open Template...` workflow showed the persistent slowdown side effect
- Replaced the native template-open file dialog with an in-app `TemplateSelectionDialog`, so template opening now uses a lightweight internal selection surface instead of the problematic native dialog path.
- Preserved full template restoration after the dialog fix:
  - curve-level settings were gradually re-enabled and verified
  - track settings were re-enabled
  - depth-track restoration was re-enabled
- Added a small delayed apply step when opening a template so the final `open_plot_from_spec(...)` call runs after the selection flow settles, reducing timing-related application fragility.
- Captured the final practical resolution:
  - keep the in-app template-selection dialog
  - keep the unified plot-spec/open-plot architecture
  - keep full template restoration enabled
  - avoid returning to the native file-open dialog for template loading unless its side effects are separately resolved
- Fixed a follow-up regression in `scripts/rendering/scroll_manager.py` where debug logging referenced `logger` without importing it.

## [2026-06-20] - Plot Scroll Chain Stabilization / 绘图滚动链路稳定性优化

- Reduced redundant header repaint signal connections in `HeaderWidget`, preventing repeated range-change callbacks from accumulating as curves are added to a track.
- Added no-op guards around scrollbar value propagation to reduce unnecessary scroll handling during fine drag operations.
- Restored image-track "refresh after settle" behavior so rapid scrollbar dragging can defer tile refresh work until scrolling stops, while still guaranteeing a final refresh when the settled depth range is unchanged.
- Adjusted tiled image viewport handling so active scrollbar dragging can avoid immediate tile-request churn and let the final settled viewport drive the visible refresh.
- Simplified `sync_viewboxes()` so the main plot `ViewBox` remains strongly synchronized while same-track overlay viewboxes are no longer redundantly forced through manual Y-range updates on every scroll step.
- Refined depth/grid visual alignment by drawing Y grid lines directly from the shared physical-depth step calculation and by positioning the depth tick cache using its own cached pixel density.
- Verified that the above changes preserve normal multi-track logging plot behavior, including mixed image/curve display, same-track multi-curve plotting, and standard interaction workflows.

## [2026-06-19] - DLIS Curve Export / DLIS 曲线导出

- Added a new `File -> Export DLIS...` workflow for exporting stored well curves back to `.dlis`.
- Introduced a dedicated export dialog with:
  - well selection on the left
  - frame/folder-grouped curve selection on the right
  - custom output file naming with well-name default
  - inline export progress shown directly inside the export dialog footer instead of a separate progress popup
- Added a new DLIS export service in `scripts/data/dlis_exporter.py` based on `dliswriter`.
- Preserved frame/folder structure during export:
  - each folder/frame is exported as a DLIS frame
  - matching depth curves are auto-included per frame when required for frame indexing
- Expanded export data-shape support:
  - 1D curves are supported
  - 2D curves are supported and round-trip through `dlisio`
  - 3D+ curves are skipped with an explicit warning instead of failing the whole export
- Added DLIS unit compatibility handling:
  - common units such as `API`, `g/cm3`, and `ohm.m` are normalized to writer-compatible values when possible
  - unsupported units are exported as blank units instead of blocking file creation
- Improved export feedback:
  - export result messages now list exported curves
  - skipped curves and unit normalization details are summarized after export
  - progress now reflects both pre-write preparation and the underlying logical-record write phase from `dliswriter`
- Updated dependency metadata to include `dliswriter`.
- Added regression coverage in `tests/test_dlis_export.py` for:
  - dialog grouping and default naming
  - frame-preserving export behavior
  - automatic depth injection
  - 2D export support
  - 3D skip behavior
  - unit normalization
  - missing dependency handling
- Current verification command:
  - `.\.venv\Scripts\python.exe -m unittest tests.test_dlis_export tests.test_tree_controller_menus tests.test_manual_table_dialog`
- Current result:
  - `Ran 13 tests ... OK`


## [2026-06-18] - Curve Explorer Integrity & Template Identity Clarification / 曲线管理完整性与模板标识澄清

- Repaired missing folder rename support in the curve explorer:
  - restored the folder `Rename` action in `scripts/ui/tree_controller.py`
  - added `DBManager.update_folder_name(...)` in `scripts/data/db_manager.py`
- Refactored explorer context-menu construction in `scripts/ui/tree_controller.py` so blank-area, well, folder, curve, and multi-selection menus are built through shared helpers instead of one long inline branch.
- Hardened folder lifecycle behavior in `scripts/data/db_manager.py`:
  - `delete_folder(...)` now recursively removes child folders before deleting the parent
  - `move_folder(...)` now rejects self-parent and descendant-cycle moves
- Expanded explorer move semantics:
  - cross-well curve transfer now carries the related depth curve with the moved/copied curve group
  - cross-well folder transfer now preserves nested folder structure in the target well
  - moved curve groups are placed into an isolated destination folder/frame instead of being forced to match the target well's existing depth index
- Added regression coverage in `tests/test_ai_tool_specs.py` and `tests/test_tree_controller_menus.py` for:
  - folder rename persistence
  - recursive folder delete
  - folder-cycle prevention
  - curve explorer menu completeness
  - cross-well curve transfer with depth carry-over
  - cross-well folder transfer with preserved subfolder hierarchy
- Clarified the current template-identity direction:
  - plot/template restoration should prefer stable curve identity (`well_id`, `curve_id`, and folder-qualified source names) over display legend text
  - display titles and real curve identifiers are now treated as separate concerns in the template lookup path
  - this avoids template reapplication drift when visible curve titles differ from the underlying stored curve name
- Current verification commands:
  - `.\.venv\Scripts\python.exe -m unittest tests.test_ai_tool_specs.DBManagerFolderRenameTests tests.test_ai_tool_specs.TreeControllerCrossWellTransferTests tests.test_ai_tool_specs.TemplateIdentityRegressionTests tests.test_tree_controller_menus`
- Current results:
  - `Ran 13 tests ... OK`

### Data Viewer Unification / Data Viewer 统一

- Replaced the old split between lightweight preview and compare-table implementations with a single table-viewing surface centered on `scripts/ui/widgets/data_viewer_widget.py`.
- Renamed the former Data Compare workflow to Data Viewer across the workspace-facing UI:
  - MDI window titles now use `Data Viewer N`
  - tree context-menu entries now use `Data Viewer`
  - related internal entry points were renamed from compare-oriented wording to viewer-oriented wording
- Removed the dedicated `DataPreviewDialog` implementation path and changed curve double-click behavior to open the unified MDI Data Viewer instead of a separate popup preview table.
- Standardized table behavior across single-curve and multi-curve viewing:
  - leading row-index column plus `Depth`
  - shared copy behavior
  - header click selects entire columns
  - optional full-source tooltip support for compared curves
- Expanded Data Viewer support for 2D curves:
  - a single 2D curve can now open directly in Data Viewer
  - 2D slices use numeric headers (`1`, `2`, `3`, ...)
  - mixed 1D/2D content on the same viewer page is still intentionally restricted
- Refined column sizing behavior for readability:
  - row-index and depth columns auto-size to content
  - regular data columns now use a stable fixed width instead of content-driven resizing
- Removed the top-level menu-bar Data Viewer entry so the viewer is opened through direct curve interaction and tree context actions rather than a standalone empty page command.
- Added and updated regression coverage for the unified viewer model and tree menu wording in:
  - `tests/test_ai_tool_specs.py`
  - `tests/test_tree_controller_menus.py`
- Current verification commands:
  - `.\.venv\Scripts\python.exe -m unittest tests.test_ai_tool_specs.DataViewerModelTests tests.test_tree_controller_menus`
- Current results:
  - `Ran 11 tests ... OK`

### Data Viewer Editing, Save Refresh, and Empty-Workspace Launchpad / Data Viewer 编辑保存刷新与空白工作区入口

- Expanded the unified Data Viewer from read-only viewing into an editable 1D curve workbench:
  - table cells in data columns can now be edited directly
  - `Reset` / `Save` actions live in a floating action pill inside the viewer
  - save behavior remains conservative and database-backed
- Refined Data Viewer save semantics around curve identity and depth handling:
  - single 1D curve pages now preserve original sample order instead of collapsing repeated depth rows through depth-key deduplication
  - save arrays are built from the source curve's own depth axis rather than from compare-style union depth rows
  - repeated-depth single-curve saves no longer silently drop intermittent samples
- Tightened multi-curve viewer rules to avoid ambiguous alignment:
  - curves now share a page only when their depth arrays match exactly
  - depth-mismatched 1D curves automatically open in a new Data Viewer page instead of being force-merged through `np.unique(...)`
  - pages that already contain a 2D curve now auto-redirect newly dropped curves into a fresh Data Viewer page rather than interrupting the user with a modal warning
- Improved save-result refresh behavior inside Data Viewer:
  - after saving, the left tree still refreshes
  - the active Data Viewer column now also refreshes its in-memory curve identity
  - overwrite saves keep the existing identity while updating the baseline data
  - save-as-new updates the viewer column to the newly created curve name / id so the page stays consistent with the database state
- Simplified save constraints to match the current product rule:
  - edited curves save back to their original well and folder
  - extra fallback logic for cross-folder depth regeneration was removed
  - save conflict handling remains a simple overwrite confirmation flow
- Added a new empty-workspace launch surface in the MDI area:
  - when no plot/data/script subwindows are open, the center workspace now shows dedicated launch tiles
  - `Plot` tile supports both click-to-open and drag-to-open behavior
  - `Data Viewer` tile supports both click-to-open and drag-to-open behavior
  - the launchpad implementation was extracted into `scripts/ui/widgets/workspace_launchpad_widget.py` for future extension with more workspace-entry tiles
- Refined the launchpad presentation and behavior:
  - launch tiles use a lightweight translucent card treatment over the empty workspace
  - tile text is centered and uses a directly assigned font in code for predictable sizing
  - launchpad visibility now refreshes correctly on first application open, not only after subwindow lifecycle changes
- Added and updated regression coverage in `tests/test_ai_tool_specs.py` for:
  - single-curve repeated-depth preservation
  - source-aligned save-array generation
  - same-depth / different-depth page-routing rules
  - 2D-to-new-page redirect behavior
  - save-result identity refresh
  - launchpad MIME parsing, click behavior, and empty-workspace visibility
- Current verification commands:
  - `.\.venv\Scripts\python.exe -m unittest tests.test_ai_tool_specs.DataViewerModelTests tests.test_ai_tool_specs.WorkspaceLaunchpadTests tests.test_tree_controller_menus`
  - `.\.venv\Scripts\python.exe -m py_compile main.py scripts/ui/widgets/data_viewer_widget.py scripts/ui/widgets/workspace_launchpad_widget.py scripts/ui/theme_manager.py`
- Current results:
  - `Ran 22 tests ... OK`

## [2026-06-06] - Plot Cache Budgeting / 绘图缓存上限控制

- Added bounded LRU behavior for the shared depth-index cache in `scripts/utils/curve_loading.py`:
  - converted `DEPTH_CACHE` from a plain dict to `OrderedDict`
  - introduced `MAX_DEPTH_CACHE_ITEMS = 32`
  - refreshes cache recency on hits and evicts the least-recently-used depth entry when the cache exceeds the item budget
- Added per-track image tile memory budgeting in `scripts/rendering/tiled_image_item.py`:
  - introduced `MAX_TILE_CACHE_BYTES_PER_TRACK = 128 * 1024 * 1024`
  - tracks estimated tile memory and last-used timestamps
  - prunes non-visible, less-recent tile images first while retaining currently needed viewport tiles
- Current verification command:
  - `.\.venv\Scripts\python.exe -m py_compile scripts\rendering\tiled_image_item.py scripts\utils\curve_loading.py`
- Current result:
  - `OK`

## [2026-05-13] - Rename-safe Plotting Resolution Refactor / Rename-safe 绘图解析重构

- Refactored plotting-related well resolution so external callers can continue using `well` by name while internal plotting flows resolve once to stable identifiers and carry only the resolved context downstream.
- Added a shared resolver in `scripts/utils/well_queries.py`:
  - `resolve_well_context(well, db_path=None, data_dir=None)`
  - returns `resolved_db_path`, `resolved_well_id`, normalized `well_name`, and an opened `DBManager`
- Updated packaged plotting entry points in `pylog_api/plotting.py` so `plot_from_db(...)` resolves the well exactly once and `_build_plot_data_list_from_db(...)` consumes the resolved bundle instead of re-inferring the well mid-path.
- Updated the legacy plotting bridge in `pylog_api/legacy_plot_bridge.py` to follow the same one-time resolution contract before delegating into the shared packaged builder.
- Added `LogWidget.set_db_source(...)` in `scripts/rendering/plot_widget.py` so plot windows keep `self.db` and `self.db_path` synchronized when the backing database changes at runtime.
- Formalized post-rename runtime synchronization in `scripts/ui/tree_controller.py`:
  - update `MainWindow.db` when it still points at the renamed database
  - update Explorer clipboard payloads that cache `db_path`
  - update open `LogWidget` instances to the renamed database path
  - update matching plot window titles for presentation consistency
- Kept existing rename behavior unchanged for users: renaming a well still renames the `.db` file, renames the companion `.h5` file when present, and rewrites H5 path references stored in curve metadata.
- Added regression coverage for the new plotting-resolution contract and runtime rename synchronization in `tests/test_ai_tool_specs.py`, including:
  - stable plotting-context resolution
  - single-resolution plotting entry behavior
  - runtime sync for open plots and clipboard state after well rename
- Current regression command:
  - `.\.venv\Scripts\python.exe -m unittest tests.test_ai_tool_specs`
- Current result:
  - `Ran 53 tests ... OK`

## [2026-04-13] - Chat Template Split Consolidation / Chat Template Split Cleanup

- Consolidated the earlier `chat_template.html` breakup into a stable split-resource layout, keeping the HTML template focused on DOM skeleton only while moving behavior and most presentation logic into dedicated resource files.
- Confirmed the active chat front-end resource boundary:
  - `plugins/ai_assistant/ui/resources/chat_template.html`
  - `plugins/ai_assistant/ui/resources/chat_styles.css`
  - `plugins/ai_assistant/ui/resources/chat_bootstrap.js`
  - `plugins/ai_assistant/ui/resources/chat_tools.js`
  - `plugins/ai_assistant/ui/resources/chat_details.js`
  - `plugins/ai_assistant/ui/resources/chat_plan.js`
  - `plugins/ai_assistant/ui/resources/chat_input.js`
  - `plugins/ai_assistant/ui/resources/chat_message.js`
- Removed additional legacy chat-template leftovers discovered during the split cleanup, including no-op helpers and unused rendering helpers that were no longer part of the live message/tool rendering path.
- Kept task progress as the single primary planning surface and continued the earlier removal of the legacy in-template todo rendering path, avoiding a second parallel task UI inside `chat_template.html`.
- Added and maintained UI regression coverage to lock in the split structure, including external stylesheet loading, split-script loading, progress-card rendering assumptions, inline-vs-block code styling, and custom toolbar tooltip behavior.
- Follow-up UI polishing after the split included:
  - compacting streaming tool-card spacing to eliminate first-tool layout jump
  - retaining borders for block code while removing borders from inline code
  - replacing native toolbar `title` tooltips with themeable in-page tooltips
  - theming and simplifying the web-chat context menu so it only exposes relevant actions

## [2026-04-09] - AI Chat UI Modernization & Streaming Flow Refinement / AI 对话 UI 现代化与流式布局精修

- Complete architectural rework of the AI chat interface using pure HTML and Vanilla JavaScript, eliminating complex UI dependencies and reducing Python event loop overhead.
- Implemented **Interleaved Streaming**: Text, reasoning, and tool execution cards now appear strictly in chronological order within the main chat bubble during active generation, restoring a natural conversational flow.
- Re-implemented the **"Archive-to-Details"** mechanism: once a task is finished, intermediate steps and tool logs are automatically moved from the main bubble to a collapsible structured `details` panel, leaving only the final conclusion visible.
- Optimized **`tool_finish`** logic: prevents trivial "Finished" messages from overwriting rich streamed summaries by prioritizing accumulated content.
- Implemented **Dynamic AI Task Planning** [Roadmap 8.3 / M3]: Transitioned from rigid, template-based 4-step plans to a model-authored dynamic architecture where the UI 1:1 reflects the agent's internal task plan.
- Enhanced **Domain Routing** [Roadmap 8.2]: Significantly improved geoscience domain detection for data analysis, statistics, and correlation tasks, ensuring accurate tool-policy alignment.
- Refined **Task Card Interaction**: Implemented a "collapsed-by-default" behavior for task progress cards to ensure a clean UI during execution, requiring manual expansion for detailed step inspection.
- Fixed rendering synchronization bugs by implementing a **state-aware redraw strategy** with cached render data, ensuring the UI accurately reflects the transition from "streaming" to "finalized."
- Significantly improved UI performance and stability for long-running agentic tasks by offloading DOM manipulation to the browser engine, mitigating `QEventDispatcherWin32` handle exhaustion risks.

## [2026-04-08] - Tool Result Contract Convergence / 工具结果契约收敛

- Unified the local tool-result contract across the main AI execution path so upper layers now consume normalized `ok`, `summary`, `content`, and `data` semantics instead of branching on legacy raw dict shapes.
- Tightened `ToolResult` normalization and updated `tool_finish` so visible output, final control signaling, and fallback summaries follow the same result contract.
- Wrapped PyLog API tools into the unified result envelope, including primary payload extraction for wells, curves, analysis results, plot metadata, and API inspection results.
- Updated policy, state, and finish handling layers to consume normalized summaries/errors instead of reading raw `message` or `final_answer` fields directly.
- Unified planning/result consumption in `chat_service.py`, `web_chat_view.py`, and `message_formatter.py`, so UI-facing tool cards and task-progress updates now work with normalized result payloads while still tolerating legacy top-level fields.
- Reworked the front-end tool-card rendering path in `chat_template.html` to correctly display object-style tool results instead of rendering them as `[object Object]`.
- Cleaned several affected files into UTF-8-safe English content to reduce repeated encoding regressions in tests, tooling, and diagnostics.
- Expanded regression coverage for normalized mapping shapes, finish-output extraction, task-progress payload extraction, web chat result normalization, and message formatting.
- Current regression command:
  - `.\.venv\Scripts\python.exe -m unittest tests.test_ai_agent_core_behaviors tests.test_ai_tool_specs`
- Current result:
  - `Ran 91 tests ... OK`

## [2026-04-07] - Plotting Pipeline Convergence & Cleanup / 绘图链路收敛与清理

- Plotting work moved beyond parameter normalization and now converges the full pipeline: curve resolution, curve loading, well/depth lookup, packaged orchestration, render payload preparation, track creation, and plot window creation/reuse.
- `pylog_api/plotting.py` now performs packaged plotting orchestration instead of acting as a thin legacy forwarder.
- Shared plotting helpers were added or expanded:
  - `scripts/utils/plot_payload_utils.py`
  - `scripts/utils/plot_track_utils.py`
  - `scripts/utils/plot_window_utils.py`
  - `scripts/utils/plot_finalize_utils.py`
  - `scripts/utils/plot_render_utils.py`
  - `scripts/utils/well_queries.py`
- `pylog_api/legacy_impl.py` was substantially thinned:
  - compatibility helpers moved to `pylog_api/compat_shims.py`
  - API forwarders moved to `pylog_api/legacy_forwarders.py`
  - DB plot orchestration moved to `pylog_api/legacy_plot_bridge.py`
  - remaining per-curve render flow moved to `scripts/utils/plot_render_utils.py`
- The PyLog MCP query path now reuses packaged/shared layers for well resolution, curve resolution, metadata lookup, curve listing, and numerical analysis.
- Fixed the anonymous-track regression so unnamed curves no longer reuse the same container when `track` is omitted.
- Regression coverage was expanded across shared curve loading, named/anonymous track behavior, window reuse, finalize scheduling, and MCP delegation.
- Current regression command:
  - `.\.venv\Scripts\python.exe -m unittest tests.test_ai_tool_specs tests.test_ai_agent_core_behaviors tests.test_ai_agent_high_risk_policy tests.test_ai_domain_router`
- Current result:
  - `Ran 88 tests ... OK`

## [2026-04-07] - AI Agent Explicit Task Planning MVP / AI Agent 显式任务规划层最小版落地

- Introduced an explicit task-planning layer built around `TaskPlan`, `TaskPlanStep`, and `TaskPlanner`.
- Connected planning state to the runtime state machine, including current step, current domain, progress payloads, and step rollback.
- Added task-progress signal flow from `api_client` through `chat_service` to the UI.
- Added a dedicated plan-progress card in the UI instead of reusing the explicit todo area.
- Shifted default planning responsibility from todo tools to the built-in planning layer.
- Fixed plan-flow issues such as lookup tools advancing to analysis, later steps skipping earlier pending steps, and small-talk requests triggering unnecessary skeleton plans.
- Added a plan enablement threshold so only clearly multi-step tasks show the planning layer.

## [2026-04-06] - AI Agent Domain Routing MVP / AI Agent 领域路由最小版落地

- Added an initial domain-routing layer so the agent can distinguish coding, scripting, geoscience, and general tasks more reliably.
- Began aligning tool selection and prompt organization with domain detection.
- Established the basis for later planning, risk policy, and tool-selection strategies.

## [2026-04-06] - AI Agent High-risk Tool Guardrails & Core Test Coverage / AI Agent 高风险工具护栏与核心测试覆盖

- Added high-risk guardrails for destructive file operations, dangerous commands, and unsafe auto-execution paths.
- Tightened pre-execution checks so risky actions fail early when prerequisites are not met.
- Expanded core behavior and high-risk policy tests for the agent runtime.

## [2026-04-06] - AI Agent ToolSpec Capability Descriptor Upgrade / AI Agent ToolSpec 能力描述升级

- Upgraded ToolSpec metadata with capability tags, domain tags, required arguments, and conditional argument rules.
- Improved the metadata foundation used by tool selection, parameter validation, prompt guidance, and planning.
- Reduced mismatch between tool descriptions and how the dispatcher understands real tool behavior.

## [2026-04-05] - AI Agent Execution Core Refactor / AI Agent 执行核心重构

- Refactored the execution core around message handling, tool execution, result propagation, and state synchronization.
- Reduced patchy branching in the main execution flow and made the core more suitable for later policy/planning integration.
- Improved maintainability of the central dispatch path.

## [2026-04-05] - AI Assistant Resource Optimization & Smart Scroll / AI 助手资源优化与智能滚动

- Optimized resource loading and UI refresh behavior in the AI assistant experience.
- Improved scrolling behavior and long-conversation readability.
- Prepared the UI for dynamic elements such as task cards and plan-progress cards.

## [2026-04-04] - Optional MCP Extension & Target-aware Verification Loop / 可选 MCP 扩展与目标感知验证闭环

- Added an optional MCP extension path so tool capabilities can gradually move toward a more unified service interface.
- Introduced a target-aware verification loop so the system more clearly knows what to verify after execution.
- Prepared the way for later tool unification, MCP adoption, and result standardization.

## [2026-04-03] - AI Coding Agent Minimum Loop & Script Tooling Fixes / AI 代码代理最小闭环与脚本工具链修复

- Added the first minimum coding-agent loop with structured runtime state, policy checks, patch editing, and verification tools.
- Fixed tool auto-discovery so newly added tools are reliably registered.
- Unified script workflows around `editor_id`, covering open, set, append, save, run, and write-then-open scenarios.
- Fixed script saving so explicit save paths are written to disk instead of remaining editor-only state.
- Improved script runtime stability by synchronizing editor caches and removing blocking WebEngine value-fetch logic.

## [2026-04-03] - Plot Engine Stabilization & AI Scripting Expert / 绘图引擎稳定化与 AI 脚本专家系统

- Fixed log-scale rendering issues by standardizing on manual log transforms and avoiding double-log conflicts.
- Added delayed first-frame synchronization to stabilize HDF5 lazy-proxy plotting.
- Improved auto-detection of resistivity log mode and explicitly excluded 2D image data from unintended log rendering.
- Added the `pylog-scripting` skill and aligned prompt guidance with the scripting expert workflow.
- Standardized statistical API naming around `analyze_data` and `analyze_curve`.
- Preserved lazy loading behavior in `pylog_api.py` by removing unnecessary eager `np.asarray()` conversions.
- Added a manual refresh action to the data browser after script-driven database changes.

## [2026-04-02] - Skill Integration & Management Refinement / Skill 接入与管理能力完善

- Improved skill lookup so tools can resolve full IDs, short names, and frontmatter names consistently.
- Added aliases to skill list results for better UI and agent readability.
- Expanded the skill service with normalization, alias parsing, fuzzy resolution, and skill creation support.
- Fixed skill deletion robustness and improved YAML frontmatter writeback compatibility.
- Added skill creation and richer skill metadata display to the settings UI.

## [2026-04-02] - AI Expert System & Path Centralization / AI 专家系统深度强化与路径架构中心化

- Upgraded skill discovery to recursive scanning so nested workflow skills can be found reliably.
- Standardized skill IDs as relative paths to avoid collisions and preserve hierarchy.
- Extended skill inspection so the agent can see skill-local files in addition to `SKILL.md`.
- Added `PathResolver` as the centralized source of truth for project, skill, and script paths.
- Hardened import-path handling to eliminate top-level relative import failures in plugin environments.
- Improved execution sandboxing, `sys.exit()` interception, matplotlib isolation, and cross-thread UI refresh stability.

## [2026-04-02] - HDF5 Architecture Migration & Metadata Enhancement / HDF5 架构深度迁移与 UI 元数据增强

- Continued the HDF5 architecture migration with stronger metadata consistency and richer UI-facing descriptors.
- Improved the mapping between stored data structures and UI metadata consumers.
- Prepared the storage layer for later query, rendering, and export standardization.

## [2026-04-02] - HDF5 Scale Sync & Load Optimization / HDF5 曲线刻度同步与加载性能优化

- Improved HDF5 scale synchronization during scroll and zoom operations.
- Reduced redundant data loading and unnecessary refresh paths.
- Stabilized interaction quality for large-depth and large-curve scenarios.

## [2026-04-01] - Scroll Debounce & H5 Read Noise Reduction / 图像滚动防抖与 H5 读取降噪优化

- Added debounce behavior around scroll-driven refresh work.
- Reduced noisy H5 reads and unnecessary trigger frequency.
- Improved smoothness and stability during high-frequency depth interactions.

## [2026-04-01] - Delete/Rename/NumPy 2 / HDF5 完整性修复

- Added or repaired HDF5 delete and rename maintenance paths.
- Addressed NumPy 2 compatibility issues in the data-processing layer.
- Reduced upgrade risk in the numerical stack.

## [2026-04-01] - Full HDF5 Architecture Migration & Storage Unification / HDF5 全量架构迁移与存储统一化

- Advanced the full HDF5 migration and unified storage conventions.
- Reduced complexity caused by mixed old/new storage models.
- Prepared the codebase for later performance and modularity work.

## [2026-04-01] - Core Rendering Engine Performance Optimization / 核心渲染引擎性能优化

- Optimized the main rendering path to reduce bottlenecks in plotting and refresh operations.
- Strengthened the rendering foundation for complex curve display, filling, and track interaction.

## [2026-04-01] - HDF5 Architecture & UI Standardization / HDF5 数据架构与 UI 主题标准化

- Continued aligning HDF5 storage architecture with UI-side standards and expectations.
- Clarified the contract between the data layer and the presentation layer.

## [2026-03-31] - AI UI Consolidation & PySide6 Component Standardization / AI 助手 UI 整合与 PySide6 组件样式标准化

- Consolidated AI-related UI entry points and reduced duplication across windows and components.
- Standardized PySide6 component styling and structure.
- Prepared the UI foundation for richer assistant-side surfaces.

## [2026-03-30] - Curve Fill Rendering Engine Optimization / 曲线填充渲染引擎优化

- Optimized curve fill rendering for both correctness and performance.
- Strengthened the basis for cross-fill, accumulative fill, and more complex track visuals.

## [2026-03-29] - Well Log Export Refinement & Manga Theme Polish / 测井图导出精修与 Manga 主题完善

- Refined well-log export behavior and improved output consistency.
- Continued visual polishing of the Manga-inspired theme.

## [2026-03-28] - Unified Web Theme Management & UI Polish / 统一 Web 主题管理与 UI 精修

- Unified theme management on the web side.
- Improved visual consistency and UI details across web surfaces.

## [2026-03-27] - Global Theme Management & Settings Standardization / 全局主题管理与设置界面标准化

- Standardized global theme management and settings organization.
- Reduced scattered style overrides and fragmented configuration logic.

## [2026-03-25] - Manual Table & Vector Export Enhancements / 手工曲线与矢量导出增强

- Renamed and improved the manual custom-curve workflow, including folder defaults, paste support, overwrite confirmation, and better file/folder handling.
- Improved explorer workflows such as creating wells from the blank-area context menu and preserving tree expansion state during refresh.
- Added clipboard export with both SVG and high-resolution PNG data for better Office integration.
- Refined depth-axis export quality with centered labels, overflow clamping, and stronger anti-aliasing.
- Added the first MCP client core, including dynamic server management, local wrapping into the tool system, and settings UI integration.
- Strengthened full lifecycle cleanup of background processes and improved async shutdown stability.

## [2026-03-24] - Asynchronous Architecture Refactor / AI 助手异步架构重构

- Migrated the assistant runtime to a fully asynchronous architecture built on `asyncio` and `qasync`.
- Reworked the worker and client stack around non-blocking OpenAI calls.
- Added a hybrid execution engine that supports both async-native tools and threaded execution of sync tools.
- Completed the architecture groundwork required for native MCP client integration.

## [2026-03-23] - Agent Loop & Prompt Optimization / AI 助手循环与提示词优化

- Introduced the explicit `tool_finish` endpoint for final answers and summaries.
- Refactored the ReAct loop and streaming parser around more controlled thought/action separation.
- Upgraded prompt structure to better distinguish reasoning display from action execution.
- Fixed final-answer synchronization so `tool_finish` results appear in normal conversation output.
- Added real-time code preview with draft-aware editing, reading, searching, running, and undo-friendly acceptance flows.

## [2026-03-22] - Architecture & Modularity Refactor / 架构优化与重构

- Broke apart major plotting, explorer, and track-management modules into more focused submodules.
- Extracted controllers and managers for drag/drop, selection, scrolling, image handling, filling, and persistence.
- Reorganized track containers into a clearer inheritance hierarchy for depth, curve, image, and accumulative-fill tracks.
- Added many regression fixes uncovered during the refactor, including over-scroll alignment, interaction handler wiring, and 2D robustness.

## [2026-03-21] - Export Logic Extraction / 导出模块提取

- Extracted export launch logic, scaling logic, and supporting render paths into dedicated modules.
- Added export support for cross-fill and accumulative-fill visuals.
- Extracted scroll, image, and fill management responsibilities out of larger plotting modules.
- Improved template persistence so track names and related state survive save/load cycles correctly.
- Modernized tool-call cards in the AI UI with syntax highlighting, copy actions, and clearer status pills.

## [2026-03-20] - Architecture & Modularity Refactor / 架构优化与重构

- Introduced more modular UI managers for menus, tree behaviors, and theme handling.
- Reduced the size and coupling of `MainWindow` by delegating responsibilities to specialized components.
- Applied DRY cleanup to repeated well-scan, well-resolution, and 2D-curve detection logic.

---

*This changelog was normalized for stability and readability. / 本变更日志已按稳定性与可读性统一整理。*
