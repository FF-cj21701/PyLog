## Notes / 说明

- This changelog now uses bilingual titles and English body text for long-term encoding stability.
- Some older entries were historically affected by mojibake. Those sections were normalized into readable English summaries while preserving dates and main themes.

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
