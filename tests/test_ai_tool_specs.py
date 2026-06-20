from __future__ import annotations
import json
import os
import sys
import tempfile
import math
import sqlite3
import numpy as np
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from plugins.ai_assistant.ai_core.tool_dispatcher import ToolDispatcher
import pylog_api
from plugins.ai_assistant.tools.help_tool import HelpTool
from plugins.ai_assistant.tools.agent_page_tool import CloseAgentPageTool, OpenAgentPageTool, UpdateAgentPageTool
from plugins.ai_assistant.tools.edit_file_tool import InsertIntoFileTool
from plugins.ai_assistant.tools.file_tool import RunScriptTool
from plugins.ai_assistant.tools.file_tool import SetScriptCodeTool
from plugins.ai_assistant.tools.file_operations import ReadFileTool, SearchInFileTool
from plugins.ai_assistant.tools.os_tool import FileSearchTool, TerminalTool
from plugins.ai_assistant.tools.patch_tool import ApplyPatchTool
from plugins.ai_assistant.tools.pylog_api_tool import AnalyzeDataTool, ListWellsTool, PlotTool
from plugins.ai_assistant.tools.search_code_tool import FindFilesTool, FindReferencesTool, FindSymbolTool, GrepCodeTool, SearchCodeTool
from plugins.ai_assistant.tools.verify_tool import RunImportCheckTool, RunLintCommandTool
from plugins.ai_assistant.tools.verify_tool import RunPythonFileTool
from scripts.data.db_manager import DBManager
from scripts.ui.widgets.workspace_launchpad_widget import parse_curve_mime_payload


class ToolSpecConsistencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatcher_uses_real_tool_required_args_for_search_code(self):
        dispatcher = ToolDispatcher([SearchCodeTool()])

        _tool, result = await dispatcher.execute("tool_search_code", {})

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["missing_required_args"], ["query"])

    async def test_dispatcher_uses_real_tool_required_args_for_apply_patch(self):
        dispatcher = ToolDispatcher([ApplyPatchTool()])

        _tool, result = await dispatcher.execute("tool_apply_patch", {"filepath": "demo.py"})

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["missing_required_args"], ["hunks"])

    def test_search_and_path_tools_expose_discovery_hints(self):
        self.assertIn("file path", SearchCodeTool().spec.usage_hint)
        self.assertIn("filepath", FindFilesTool().spec.usage_hint)
        self.assertIn("editing code", FindSymbolTool().spec.usage_hint)
        self.assertIn("impact", FindReferencesTool().spec.usage_hint)

    def test_required_args_are_declared_for_real_tools(self):
        self.assertEqual(HelpTool().spec.get_required_args(), ["query"])
        self.assertEqual(GrepCodeTool().spec.get_required_args(), ["pattern"])
        self.assertEqual(RunImportCheckTool().spec.get_required_args(), ["filepath"])
        self.assertEqual(TerminalTool().spec.get_required_args(), ["command"])
        self.assertEqual(FileSearchTool().spec.get_required_args(), ["pattern"])
        self.assertEqual(ReadFileTool().spec.get_required_args(), ["file_path"])
        self.assertEqual(SearchInFileTool().spec.get_required_args(), ["file_path", "pattern"])
        self.assertEqual(OpenAgentPageTool().spec.get_required_args(), ["page_id", "title"])
        self.assertEqual(UpdateAgentPageTool().spec.get_required_args(), ["page_id"])
        self.assertEqual(CloseAgentPageTool().spec.get_required_args(), ["page_id"])

    def test_real_tools_expose_conditional_argument_rules(self):
        insert_rules = InsertIntoFileTool().spec.get_argument_rules()
        lint_rules = RunLintCommandTool().spec.get_argument_rules()
        run_script_rules = RunScriptTool().spec.get_argument_rules()
        plot_rules = PlotTool().spec.get_argument_rules()

        self.assertTrue(any(rule.get("type") == "exactly_one_of" for rule in insert_rules))
        self.assertTrue(any(rule.get("type") == "requires_when" for rule in lint_rules))
        self.assertTrue(any(rule.get("type") == "at_least_one_of" for rule in run_script_rules))
        self.assertTrue(any(rule.get("type") == "at_least_one_of" for rule in plot_rules))
        self.assertTrue(any(rule.get("type") == "requires_when" for rule in plot_rules))

    def test_insert_into_file_tool_accepts_tool_executor_dependency(self):
        tool = InsertIntoFileTool(main_window=None, tool_executor=object())

        self.assertIsNotNone(tool.tool_executor)

    def test_list_wells_tool_wraps_primary_data_into_unified_result_shape(self):
        tool = ListWellsTool()

        with patch("pylog_api.list_wells", return_value={"ok": True, "wells": [{"name": "A1"}]}):
            result = tool.execute()

        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("data"), [{"name": "A1"}])
        self.assertIn("wells", result)

    def test_analyze_data_tool_wraps_analysis_into_data_field(self):
        tool = AnalyzeDataTool()

        with patch("pylog_api.analyze_data", return_value={"mean": 12.5, "count": 4}):
            result = tool.execute(values=[10, 12, 13, 15])

        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("data"), {"mean": 12.5, "count": 4})
        self.assertEqual(result.get("analysis"), {"mean": 12.5, "count": 4})


class PylogApiOptionalDbPathTests(unittest.TestCase):
    def test_pylog_api_import_now_resolves_to_package_interface(self):
        self.assertTrue(pylog_api.__file__.lower().endswith("__init__.py"), pylog_api.__file__)
        self.assertTrue(callable(pylog_api.analyze_curve))
        self.assertTrue(callable(pylog_api.get_curve_data))
        self.assertTrue(callable(pylog_api.list_curves))
        self.assertTrue(callable(pylog_api.get_curve_info))
        self.assertTrue(callable(pylog_api.list_wells))
        self.assertTrue(callable(pylog_api.get_well_info))
        self.assertTrue(callable(pylog_api.inspect_api))
        self.assertTrue(callable(pylog_api.get_depth_data))
        self.assertTrue(callable(pylog_api.save_curve))
        self.assertTrue(callable(pylog_api.plot))
        self.assertTrue(callable(pylog_api.plot_from_db))
        self.assertTrue(callable(pylog_api.plot_log_curves))
        self.assertEqual(pylog_api.inspect_api.__module__, "pylog_api.api_reflection")
        self.assertEqual(pylog_api.get_depth_data.__module__, "pylog_api.depth")
        self.assertEqual(pylog_api.list_wells.__module__, "pylog_api.well_info")
        self.assertEqual(pylog_api.get_well_info.__module__, "pylog_api.well_info")
        self.assertEqual(pylog_api.list_curves.__module__, "pylog_api.data_access")
        self.assertEqual(pylog_api.get_curve_info.__module__, "pylog_api.data_access")
        self.assertEqual(pylog_api.get_curve_data.__module__, "pylog_api.data_access")
        self.assertEqual(pylog_api.analyze_curve.__module__, "pylog_api.analysis")
        self.assertEqual(pylog_api.analyze_data.__module__, "pylog_api.analysis")
        self.assertEqual(pylog_api.save_curve.__module__, "pylog_api.writeback")
        self.assertEqual(pylog_api.plot.__module__, "pylog_api.plotting")
        self.assertEqual(pylog_api.plot_from_db.__module__, "pylog_api.plotting")
        self.assertEqual(pylog_api.plot_log_curves.__module__, "pylog_api.plotting")

    def test_inspect_api_uses_packaged_metadata_registry(self):
        result = pylog_api.inspect_api("save_curve")

        self.assertEqual(pylog_api.inspect_api.__module__, "pylog_api.api_reflection")
        self.assertEqual(result.get("name"), "save_curve")
        self.assertIn("db_path", result.get("parameters", {}))

    def test_save_curve_uses_packaged_writeback_module(self):
        self.assertEqual(pylog_api.save_curve.__module__, "pylog_api.writeback")

    @staticmethod
    def _pick_existing_curve_name(well_name):
        curves = pylog_api.list_curves(well_name)
        assert curves.get("ok"), curves
        assert curves.get("curves"), curves
        curve = next(
            (
                item for item in curves["curves"]
                if item.get("folder") and item.get("name")
            ),
            curves["curves"][0],
        )
        return (
            f"{curve['folder']}/{curve['name']}"
            if curve.get("folder")
            else curve["name"]
        ), curve

    def test_list_curves_can_resolve_db_path_from_project_data_when_omitted(self):
        wells = pylog_api.list_wells()
        self.assertTrue(wells.get("ok"), wells)
        self.assertTrue(wells.get("wells"), wells)

        first = wells["wells"][0]
        well_name = first[1] if isinstance(first, (list, tuple)) else first["name"]
        result = pylog_api.list_curves(well_name)

        self.assertTrue(result.get("ok"), result)
        self.assertIsInstance(result.get("curves"), list)

    def test_get_curve_info_can_resolve_db_path_from_project_data_when_omitted(self):
        wells = pylog_api.list_wells()
        self.assertTrue(wells.get("ok"), wells)
        first = wells["wells"][0]
        well_name = first[1] if isinstance(first, (list, tuple)) else first["name"]
        curve_name, curve = self._pick_existing_curve_name(well_name)

        result = pylog_api.get_curve_info(well_name, curve_name)

        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("name"), curve["name"])

    def test_get_curve_data_can_resolve_db_path_from_project_data_when_omitted(self):
        wells = pylog_api.list_wells()
        self.assertTrue(wells.get("ok"), wells)
        first = wells["wells"][0]
        well_name = first[1] if isinstance(first, (list, tuple)) else first["name"]
        curve_name, _curve = self._pick_existing_curve_name(well_name)

        result = pylog_api.get_curve_data(well_name, curve_name)

        self.assertFalse(isinstance(result, dict) and not result.get("ok", True), result)

    def test_analyze_curve_can_resolve_db_path_from_project_data_when_omitted(self):
        wells = pylog_api.list_wells()
        self.assertTrue(wells.get("ok"), wells)
        first = wells["wells"][0]
        well_name = first[1] if isinstance(first, (list, tuple)) else first["name"]
        curve_name, _curve = self._pick_existing_curve_name(well_name)

        result = pylog_api.analyze_curve(well_name, curve_name)

        self.assertTrue(result.get("ok"), result)
        self.assertIn("count", result)

    def test_plot_can_resolve_db_path_from_project_data_when_omitted(self):
        wells = pylog_api.list_wells()
        self.assertTrue(wells.get("ok"), wells)
        first = wells["wells"][0]
        well_name = first[1] if isinstance(first, (list, tuple)) else first["name"]
        curve_name, _curve = self._pick_existing_curve_name(well_name)

        with patch("pylog_api.plotting.create_plot") as mock_create_plot:
            mock_create_plot.return_value = {"ok": True, "title": "test-plot", "created_tracks": []}
            result = pylog_api.plot(well=well_name, curves=[curve_name], title="test-plot")

        self.assertTrue(result.get("ok"), result)
        self.assertIn("Successfully plotted", result.get("message", ""))
        mock_create_plot.assert_called_once()

    def test_plot_from_db_uses_packaged_plotting_module(self):
        self.assertEqual(pylog_api.plot.__module__, "pylog_api.plotting")
        self.assertEqual(pylog_api.plot_from_db.__module__, "pylog_api.plotting")

    def test_resolve_well_context_returns_stable_plotting_bundle(self):
        from scripts.utils.well_queries import resolve_well_context

        wells = pylog_api.list_wells()
        self.assertTrue(wells.get("ok"), wells)
        first = wells["wells"][0]
        well_name = first[1] if isinstance(first, (list, tuple)) else first["name"]

        context, error = resolve_well_context(well_name)

        self.assertIsNone(error, error)
        self.assertEqual(context["well_name"], well_name)
        self.assertTrue(context["resolved_db_path"].lower().endswith(".db"))
        self.assertIsInstance(context["resolved_well_id"], int)
        self.assertEqual(getattr(context["db"], "db_path", None), context["resolved_db_path"])

    def test_plot_from_db_resolves_well_once_before_building(self):
        from pylog_api import plotting

        context = {
            "resolved_db_path": "data/demo.db",
            "resolved_well_id": 7,
            "well_name": "Demo",
            "db": object(),
        }
        with patch.object(plotting, "resolve_well_context", return_value=(context, None)) as mock_resolve, patch.object(
            plotting,
            "_build_plot_data_list_from_db",
            return_value={"ok": True, "data_list": [{"name": "GR", "values": [1], "depth": [1]}]},
        ) as mock_build, patch.object(
            plotting,
            "_build_plot_spec_from_db_curves",
            return_value={"ok": True, "plot_spec": {"title": "demo", "tracks": []}},
        ) as mock_spec_build, patch.object(
            plotting,
            "create_plot",
            return_value={"ok": True, "title": "demo", "created_tracks": []},
        ) as mock_create_plot:
            result = plotting.plot_from_db(well="Demo", curves=["GR"], db_path=None, title="demo")

        self.assertTrue(result.get("ok"), result)
        mock_resolve.assert_called_once_with("Demo", db_path=None)
        mock_build.assert_called_once()
        self.assertIs(mock_build.call_args.args[0], context)
        mock_spec_build.assert_called_once()
        self.assertIs(mock_spec_build.call_args.args[0], context)
        mock_create_plot.assert_called_once()

    def test_legacy_plot_from_db_uses_packaged_builder(self):
        from pylog_api.core import load_legacy_module

        legacy = load_legacy_module()
        context = {
            "resolved_db_path": "demo.db",
            "resolved_well_id": 7,
            "well_name": "Demo",
            "db": object(),
        }
        with patch("pylog_api.legacy_plot_bridge.resolve_well_context", return_value=(context, None)), patch(
            "pylog_api.plotting._build_plot_data_list_from_db"
        ) as mock_build, patch(
            "pylog_api.legacy_impl._plot_log_curves"
        ) as mock_render:
            mock_build.return_value = {"ok": True, "data_list": [{"name": "GR", "values": [1], "depth": [1]}]}
            mock_render.return_value = {"ok": True, "message": "legacy-render"}

            result = legacy._plot_from_db(well="Demo", curves=["GR"], db_path="demo.db")

        self.assertTrue(result.get("ok"), result)
        mock_build.assert_called_once()
        self.assertIs(mock_build.call_args.args[0], context)
        mock_render.assert_called_once()

    def test_legacy_plot_uses_packaged_plotting_entry(self):
        from pylog_api.core import load_legacy_module

        legacy = load_legacy_module()
        with patch("pylog_api.plotting.plot") as mock_plot:
            mock_plot.return_value = {"ok": True, "message": "packaged-plot"}

            result = legacy._original_plot(well="Demo", curves=["GR"], db_path="demo.db")

        self.assertTrue(result.get("ok"), result)
        mock_plot.assert_called_once()

    def test_list_project_wells_supports_explicit_data_dir(self):
        from scripts.utils.well_queries import list_project_wells

        result = list_project_wells(data_dir=os.path.join(PROJECT_ROOT, "data"))

        self.assertTrue(result.get("ok"), result)
        self.assertTrue(result.get("wells"), result)

    def test_mcp_get_curve_info_uses_packaged_data_access(self):
        from plugins.ai_assistant.mcp_servers import pylog_mcp_server

        with patch.object(
            pylog_mcp_server,
            "packaged_get_curve_info",
            return_value={"ok": True, "name": "GR"},
        ) as mock_get_curve_info:
            result = pylog_mcp_server.get_curve_info("Demo", "GR", db_path="data/demo.db")

        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("name"), "GR")
        mock_get_curve_info.assert_called_once()
        self.assertTrue(mock_get_curve_info.call_args.kwargs["db_path"].lower().endswith("data\\demo.db"))

    def test_shared_curve_loading_matches_manual_fetch_contract(self):
        from scripts.utils.curve_loading import load_curve_bundle_for_plot
        from scripts.data.db_manager import DBManager
        from pylog_api.core import load_legacy_module
        from pylog_api import list_wells, list_curves
        from scripts.utils.well_queries import resolve_optional_db_path_for_well

        wells = list_wells()
        self.assertTrue(wells.get("ok"), wells)
        first = wells["wells"][0]
        well_name = first[1] if isinstance(first, (list, tuple)) else first["name"]

        curves = list_curves(well_name)
        self.assertTrue(curves.get("ok"), curves)
        first_curve = curves["curves"][0]
        legacy = load_legacy_module()
        db_path, resolution_error = resolve_optional_db_path_for_well(well_name, db_path=None)
        self.assertIsNone(resolution_error, resolution_error)
        db = DBManager(db_path)
        well_id, error_info = legacy._resolve_well_id(db, well_name)
        self.assertIsNotNone(well_id, error_info)
        result = load_curve_bundle_for_plot(
            db.db_path,
            well_id,
            first_curve["id"],
            preferences={"cmap": "thermal", "null_color": "Auto"},
            db=db,
        )

        self.assertTrue(result.get("ok"), result)
        self.assertEqual(len(result["data"]), len(result["depth"]))
        self.assertEqual(result["info"]["curve_id"], first_curve["id"])
        self.assertEqual(result["info"]["well_id"], well_id)

    def test_legacy_optional_db_path_wrapper_delegates_to_shared_helper(self):
        from pylog_api.core import load_legacy_module
        from scripts.utils.well_queries import resolve_optional_db_path_for_well

        wells = pylog_api.list_wells()
        self.assertTrue(wells.get("ok"), wells)
        first = wells["wells"][0]
        well_name = first[1] if isinstance(first, (list, tuple)) else first["name"]

        shared_db_path, shared_error = resolve_optional_db_path_for_well(well_name, db_path=None)
        self.assertIsNone(shared_error, shared_error)

        legacy = load_legacy_module()
        legacy_db_path, legacy_error = legacy._resolve_optional_db_path_for_well(well_name, db_path=None)

        self.assertIsNone(legacy_error, legacy_error)
        self.assertEqual(legacy_db_path, shared_db_path)

    def test_runtime_well_sync_updates_open_plot_widgets_and_clipboard(self):
        from scripts.ui.tree_controller import TreeController

        class DummyLogWidget:
            def __init__(self):
                self.received = []
                self.db_path = "data/OldWell.db"
                self.db = type("Db", (), {"db_path": "data/OldWell.db"})()

            def set_db_source(self, db_path):
                self.received.append(db_path)

        class DummySubWindow:
            def __init__(self, widget, title):
                self._widget = widget
                self._title = title

            def widget(self):
                return self._widget

            def windowTitle(self):
                return self._title

            def setWindowTitle(self, title):
                self._title = title

        class DummyMdiArea:
            def __init__(self, subwindows):
                self._subwindows = subwindows

            def subWindowList(self):
                return self._subwindows

        class DummyMainWindow:
            def __init__(self, subwindows):
                self.db = type("Db", (), {"db_path": "data/OldWell.db"})()
                self.explorer_clipboard = {
                    "db_path": "data/OldWell.db",
                    "items": [{"db_path": "data/OldWell.db", "id": 1}],
                }
                self.mdi_area = DummyMdiArea(subwindows)

        plot_widget = DummyLogWidget()
        subwindow = DummySubWindow(plot_widget, "Plot: OldWell")
        mw = DummyMainWindow([subwindow])
        controller = TreeController(mw)

        with patch("scripts.ui.tree_controller.LogWidget", DummyLogWidget), patch(
            "scripts.ui.tree_controller.DBManager",
            side_effect=lambda path: type("Db", (), {"db_path": path})(),
        ):
            controller._sync_runtime_well_references("data/OldWell.db", "data/NewWell.db", "NewWell")

        self.assertEqual(getattr(mw.db, "db_path", None), "data/NewWell.db")
        self.assertEqual(mw.explorer_clipboard["db_path"], "data/NewWell.db")
        self.assertEqual(mw.explorer_clipboard["items"][0]["db_path"], "data/NewWell.db")
        self.assertEqual(plot_widget.received, ["data/NewWell.db"])
        self.assertEqual(subwindow.windowTitle(), "Plot: NewWell")


class DBManagerFolderRenameTests(unittest.TestCase):
    def test_update_folder_name_persists_new_name_in_sqlite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "folder_rename_test.db")
            db = DBManager(db_path)
            well_id = db.save_well("DemoWell")
            folder_id = db.create_folder(well_id, "OldFolder")

            result = db.update_folder_name(folder_id, "RenamedFolder")

            self.assertTrue(result)

            conn = sqlite3.connect(db_path)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM folders WHERE id=?", (folder_id,))
                row = cursor.fetchone()
            finally:
                conn.close()

            self.assertEqual(row[0], "RenamedFolder")

    def test_delete_folder_recursively_removes_child_folders(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "folder_delete_test.db")
            db = DBManager(db_path)
            well_id = db.save_well("DemoWell")
            parent_id = db.create_folder(well_id, "ParentFolder")
            child_id = db.create_folder(well_id, "ChildFolder", parent_id=parent_id)

            db.delete_folder(parent_id)

            conn = sqlite3.connect(db_path)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM folders WHERE id IN (?, ?)", (parent_id, child_id))
                remaining = cursor.fetchone()[0]
            finally:
                conn.close()

            self.assertEqual(remaining, 0)

    def test_move_folder_rejects_self_parent_cycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "folder_move_self_cycle.db")
            db = DBManager(db_path)
            well_id = db.save_well("DemoWell")
            folder_id = db.create_folder(well_id, "Root")

            db.move_folder(folder_id, folder_id)

            folder_row = db.get_folder(folder_id)
            self.assertIsNone(folder_row[3])

    def test_move_folder_rejects_descendant_cycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "folder_move_desc_cycle.db")
            db = DBManager(db_path)
            well_id = db.save_well("DemoWell")
            root_id = db.create_folder(well_id, "Root")
            child_id = db.create_folder(well_id, "Child", parent_id=root_id)
            grandchild_id = db.create_folder(well_id, "GrandChild", parent_id=child_id)

            db.move_folder(root_id, grandchild_id)

            root_row = db.get_folder(root_id)
            child_row = db.get_folder(child_id)
            grandchild_row = db.get_folder(grandchild_id)
            self.assertIsNone(root_row[3])
            self.assertEqual(child_row[3], root_id)
            self.assertEqual(grandchild_row[3], child_id)


class TreeControllerCrossWellTransferTests(unittest.TestCase):
    def test_cross_well_cut_transfers_curve_with_depth_into_target_folder(self):
        from scripts.ui.tree_controller import TreeController

        class DummyStatusBar:
            def __init__(self):
                self.messages = []

            def showMessage(self, message, timeout=0):
                self.messages.append((message, timeout))

        class DummyMainWindow:
            def __init__(self, clipboard):
                self.explorer_clipboard = clipboard
                self._status_bar = DummyStatusBar()

            def statusBar(self):
                return self._status_bar

        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "Source.db")
            target_path = os.path.join(tmpdir, "Target.db")

            source_db = DBManager(source_path)
            source_well_id = source_db.save_well("SourceWell")
            source_folder_id = source_db.create_folder(source_well_id, "FRAME1")
            source_db.save_curve(source_well_id, "DEPT", "m", np.array([1000.0, 1000.5, 1001.0]), source_folder_id)
            source_db.save_curve(source_well_id, "GR", "API", np.array([80.0, 81.0, 82.0]), source_folder_id)

            target_db = DBManager(target_path)
            target_well_id = target_db.save_well("TargetWell")

            source_curves = source_db.get_curves(source_well_id)
            gr_row = next(row for row in source_curves if row[1] == "GR")
            clipboard = {
                "items": [
                    {
                        "type": "curve",
                        "id": gr_row[0],
                        "name": "GR",
                        "folder": "FRAME1",
                        "well_id": source_well_id,
                        "db_path": source_path,
                    }
                ],
                "op": "cut",
                "db_path": source_path,
            }

            controller = TreeController(DummyMainWindow(clipboard))
            controller.refresh_tree = lambda *args, **kwargs: None

            controller.handle_paste(target_path, target_well_id, None)

            moved_target_db = DBManager(target_path)
            target_folders = moved_target_db.get_folders(target_well_id)
            self.assertEqual(len(target_folders), 1)
            self.assertEqual(target_folders[0][1], "FRAME1")

            target_curves = moved_target_db.get_curves(target_well_id)
            self.assertEqual(sorted(row[1] for row in target_curves), ["DEPT", "GR"])

            moved_source_db = DBManager(source_path)
            remaining_source_curves = moved_source_db.get_curves(source_well_id)
            self.assertEqual(remaining_source_curves, [])

    def test_cross_well_folder_transfer_preserves_subfolder_structure(self):
        from scripts.ui.tree_controller import TreeController

        class DummyStatusBar:
            def showMessage(self, message, timeout=0):
                return None

        class DummyMainWindow:
            def __init__(self, clipboard):
                self.explorer_clipboard = clipboard
                self._status_bar = DummyStatusBar()

            def statusBar(self):
                return self._status_bar

        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "Source.db")
            target_path = os.path.join(tmpdir, "Target.db")

            source_db = DBManager(source_path)
            source_well_id = source_db.save_well("SourceWell")
            root_folder_id = source_db.create_folder(source_well_id, "FRAME1")
            child_folder_id = source_db.create_folder(source_well_id, "Sub1", parent_id=root_folder_id)
            source_db.save_curve(source_well_id, "DEPT", "m", np.array([1000.0, 1000.5]), child_folder_id)
            source_db.save_curve(source_well_id, "GR", "API", np.array([80.0, 81.0]), child_folder_id)

            target_db = DBManager(target_path)
            target_well_id = target_db.save_well("TargetWell")

            clipboard = {
                "items": [
                    {
                        "type": "folder",
                        "id": root_folder_id,
                        "name": "FRAME1",
                        "well_id": source_well_id,
                        "db_path": source_path,
                    }
                ],
                "op": "copy",
                "db_path": source_path,
            }

            controller = TreeController(DummyMainWindow(clipboard))
            controller.refresh_tree = lambda *args, **kwargs: None

            controller.handle_paste(target_path, target_well_id, None)

            moved_target_db = DBManager(target_path)
            target_folders = moved_target_db.get_folders(target_well_id)
            folder_by_name = {name: (fid, pid) for fid, name, pid in target_folders}
            self.assertIn("FRAME1", folder_by_name)
            self.assertIn("Sub1", folder_by_name)
            self.assertEqual(folder_by_name["Sub1"][1], folder_by_name["FRAME1"][0])

            target_curves = moved_target_db.get_curves(target_well_id)
            self.assertEqual(sorted(row[1] for row in target_curves), ["DEPT", "GR"])


class TemplateIdentityRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_curve_track_state_preserves_curve_identity_fields(self):
        from scripts.tracks.track_container import CurveTrackContainer

        track = CurveTrackContainer()
        track.plot_widget.curves = [
            {
                "info": {
                    "well_id": 7,
                    "curve_id": 42,
                    "name": "GR",
                    "title": "Gamma Ray",
                    "folder": "FRAME1",
                    "unit": "API",
                }
            }
        ]

        state = track.get_state()

        self.assertEqual(state["curves"][0]["well_id"], 7)
        self.assertEqual(state["curves"][0]["curve_id"], 42)
        self.assertEqual(state["curves"][0]["name"], "GR")
        self.assertEqual(state["curves"][0]["title"], "Gamma Ray")

    def test_template_identity_lookup_prefers_stable_curve_identity_over_title(self):
        from scripts.data.template_manager import TemplateManager

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "template_identity.db")
            db = DBManager(db_path)
            well_id = db.save_well("DemoWell")
            folder_id = db.create_folder(well_id, "FRAME1")
            db.save_curve(well_id, "GR", "API", np.array([80.0, 81.0]), folder_id)

            curve_id = next(row[0] for row in db.get_curves(well_id) if row[1] == "GR")
            curve_cfg = {
                "well_id": well_id,
                "curve_id": curve_id,
                "name": "GR",
                "title": "Gamma Ray",
                "folder": "FRAME1",
            }

            resolved = TemplateManager._find_curve_by_identity(db, curve_cfg, well_id=well_id)

            self.assertEqual(resolved, (well_id, curve_id))


class SettingsDialogPerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_unified_settings_dialog_initializes(self):
        from scripts.ui.plot_dialogs import UnifiedSettingsDialog

        dlg = UnifiedSettingsDialog()

        self.assertEqual(dlg.content_stack.count(), 5)
        self.assertIs(dlg.scroll_area.widget(), dlg.content_stack)
        self.assertIsNotNone(dlg.line_curve_w)
        self.assertIsNotNone(dlg.line_track_w)


class DataViewerModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_multi_curve_model_formats_union_rows(self):
        from PySide6.QtCore import Qt
        from scripts.data.table_data import CurveTableModel, MultiCurveTableModel

        preview_model = CurveTableModel()
        preview_model.update_data(np.array([100.0, 101.0]), np.array([10.0, 20.0]))
        self.assertEqual(preview_model.columnCount(), 3)
        self.assertEqual(preview_model.headerData(0, Qt.Horizontal), "")
        self.assertEqual(preview_model.headerData(1, Qt.Horizontal), "Depth")
        self.assertEqual(preview_model.headerData(2, Qt.Horizontal), "1")
        self.assertEqual(preview_model.data(preview_model.index(0, 0), Qt.DisplayRole), "1")
        self.assertEqual(preview_model.data(preview_model.index(0, 1), Qt.DisplayRole), "100.0000")
        self.assertEqual(preview_model.data(preview_model.index(0, 2), Qt.DisplayRole), "10.0000")

        model = MultiCurveTableModel()
        model.set_viewer_data(
            np.array([100.0, 101.0, 102.0]),
            [
                {"label": "GR", "tooltip": "WellA/FrameA/GR", "folder_name": "FrameA", "values": [10.0, None, 30.0]},
                {"label": "GR", "tooltip": "WellB/FrameB/GR", "folder_name": "FrameB", "values": [None, 20.0, 40.0]},
            ],
        )

        self.assertEqual(model.rowCount(), 3)
        self.assertEqual(model.columnCount(), 4)
        self.assertEqual(model.headerData(0, Qt.Horizontal), "")
        self.assertEqual(model.headerData(1, Qt.Horizontal), "Depth")
        self.assertEqual(model.headerData(2, Qt.Horizontal), "GR")
        self.assertEqual(model.headerData(2, Qt.Horizontal, Qt.ToolTipRole), "WellA/FrameA/GR")
        model.toggle_header_expanded(2)
        self.assertEqual(model.headerData(2, Qt.Horizontal), "GR/FrameA")
        self.assertEqual(model.data(model.index(0, 0), Qt.DisplayRole), "1")
        self.assertEqual(model.data(model.index(0, 1), Qt.DisplayRole), "100.0000")
        self.assertEqual(model.data(model.index(1, 2), Qt.DisplayRole), "")
        self.assertEqual(model.data(model.index(1, 3), Qt.DisplayRole), "20.0000")
        self.assertEqual(model.data(model.index(0, 2), Qt.EditRole), "10.0")
        self.assertEqual(model.data(model.index(1, 2), Qt.EditRole), "")
        self.assertFalse(model.flags(model.index(0, 1)) & Qt.ItemIsEditable)
        self.assertTrue(model.flags(model.index(0, 2)) & Qt.ItemIsEditable)
        self.assertTrue(model.setData(model.index(1, 2), "22.5"))
        self.assertEqual(model.data(model.index(1, 2), Qt.DisplayRole), "22.5000")
        self.assertTrue(model.setData(model.index(1, 2), ""))
        self.assertEqual(model.data(model.index(1, 2), Qt.DisplayRole), "")
        self.assertFalse(model.setData(model.index(1, 2), "abc"))

    def test_curve_table_model_supports_2d_with_index_column(self):
        from PySide6.QtCore import Qt
        from scripts.data.table_data import CurveTableModel

        model = CurveTableModel()
        model.update_data(np.array([100.0, 101.0]), np.array([[1.0, 2.0], [3.0, 4.0]]))

        self.assertEqual(model.columnCount(), 4)
        self.assertEqual(model.headerData(2, Qt.Horizontal), "1")
        self.assertEqual(model.headerData(3, Qt.Horizontal), "2")
        self.assertEqual(model.data(model.index(0, 0), Qt.DisplayRole), "1")
        self.assertEqual(model.data(model.index(0, 1), Qt.DisplayRole), "100.0000")
        self.assertEqual(model.data(model.index(0, 2), Qt.DisplayRole), "1.0000")
        self.assertEqual(model.data(model.index(0, 3), Qt.DisplayRole), "2.0000")

    def test_data_viewer_widget_rebuilds_matching_depth_columns(self):
        from PySide6.QtCore import Qt
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        widget = DataViewerWidget()
        widget._curve_entries = [
            {
                "db_path": "a.db",
                "well_id": 1,
                "curve_id": 10,
                "well_name": "WellA",
                "curve_name": "GR",
                "label": "GR",
                "tooltip": "WellA/FolderA/GR",
                "folder_name": "FolderA",
                "depth": np.array([100.0, 101.0]),
                "data": np.array([10.0, 11.0]),
            },
            {
                "db_path": "b.db",
                "well_id": 2,
                "curve_id": 11,
                "well_name": "WellB",
                "curve_name": "GR",
                "label": "GR",
                "tooltip": "WellB/FolderB/GR",
                "folder_name": "FolderB",
                "depth": np.array([100.0, 101.0]),
                "data": np.array([21.0, 22.0]),
            },
        ]

        widget._rebuild_model()

        self.assertEqual(widget.model.rowCount(), 2)
        self.assertEqual(widget.model.columnCount(), 4)
        self.assertEqual(widget.model.data(widget.model.index(0, 0), Qt.DisplayRole), "1")
        self.assertEqual(widget.model.data(widget.model.index(0, 2), Qt.DisplayRole), "10.0000")
        self.assertEqual(widget.model.data(widget.model.index(0, 3), Qt.DisplayRole), "21.0000")
        self.assertEqual(widget.model.data(widget.model.index(1, 3), Qt.DisplayRole), "22.0000")

    def test_data_viewer_widget_formats_single_2d_curve_like_preview(self):
        from PySide6.QtCore import Qt
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        widget = DataViewerWidget()
        widget._curve_entries = [
            {
                "db_path": "a.db",
                "well_id": 1,
                "curve_id": 10,
                "well_name": "WellA",
                "curve_name": "IMG",
                "label": "IMG",
                "tooltip": "WellA/FrameA/IMG",
                "folder_name": "FrameA",
                "depth": np.array([100.0, 101.0]),
                "data": np.array([[1.0, 2.0], [3.0, 4.0]]),
            }
        ]

        widget._rebuild_model()

        self.assertEqual(widget.model.columnCount(), 4)
        self.assertEqual(widget.model.headerData(2, Qt.Horizontal), "1")
        self.assertEqual(widget.model.headerData(3, Qt.Horizontal), "2")
        self.assertEqual(widget.model.data(widget.model.index(0, 2), Qt.DisplayRole), "1.0000")
        self.assertEqual(widget.model.data(widget.model.index(0, 3), Qt.DisplayRole), "2.0000")

    def test_data_viewer_widget_detects_duplicate_curve(self):
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        widget = DataViewerWidget()
        widget._curve_entries = [
            {
                "db_path": "a.db",
                "well_id": 1,
                "curve_id": 10,
                "well_name": "WellA",
                "curve_name": "GR",
                "label": "GR",
                "tooltip": "WellA/FolderA/GR",
                "folder_name": "FolderA",
                "depth": np.array([100.0]),
                "data": np.array([10.0]),
            }
        ]

        self.assertTrue(widget._has_curve("a.db", 1, 10))
        self.assertFalse(widget._has_curve("a.db", 1, 11))

    def test_data_viewer_dirty_and_reset_follow_model_edits(self):
        from PySide6.QtCore import Qt
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        widget = DataViewerWidget()
        widget._curve_entries = [
            {
                "db_path": "a.db",
                "well_id": 1,
                "curve_id": 10,
                "well_name": "WellA",
                "curve_name": "GR",
                "label": "GR",
                "tooltip": "WellA/FolderA/GR",
                "folder_name": "FolderA",
                "depth": np.array([100.0, 101.0]),
                "data": np.array([10.0, 11.0]),
            }
        ]
        widget._rebuild_model()

        self.assertFalse(widget._dirty)
        self.assertTrue(widget.model.setData(widget.model.index(0, 2), "15"))
        self.assertTrue(widget._dirty)

        with patch("scripts.ui.widgets.data_viewer_widget.ThemeDialog.confirm", return_value=True):
            widget.reset_changes()

        self.assertFalse(widget._dirty)
        self.assertEqual(widget.model.data(widget.model.index(0, 2), Qt.DisplayRole), "10.0000")

    def test_data_viewer_can_paste_clipboard_values_into_curve_cells(self):
        from PySide6.QtCore import Qt
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        widget = DataViewerWidget()
        widget._curve_entries = [
            {
                "db_path": "a.db",
                "well_id": 1,
                "curve_id": 10,
                "well_name": "WellA",
                "curve_name": "GR",
                "label": "GR",
                "tooltip": "WellA/FolderA/GR",
                "folder_name": "FolderA",
                "depth": np.array([100.0, 101.0, 102.0]),
                "data": np.array([10.0, 11.0, 12.0]),
            }
        ]
        widget._rebuild_model()
        widget.table.setCurrentIndex(widget.model.index(1, 2))

        with patch("scripts.ui.widgets.data_viewer_widget.QApplication.clipboard") as mock_clipboard:
            mock_clipboard.return_value.text.return_value = "21\n22"
            self.assertTrue(widget.paste_from_clipboard())

        self.assertEqual(widget.model.data(widget.model.index(1, 2), Qt.DisplayRole), "21.0000")
        self.assertEqual(widget.model.data(widget.model.index(2, 2), Qt.DisplayRole), "22.0000")
        selected = {(index.row(), index.column()) for index in widget.table.selectionModel().selectedIndexes()}
        self.assertEqual(selected, {(1, 2), (2, 2)})

    def test_data_viewer_refreshes_tree_after_save(self):
        from PySide6.QtWidgets import QWidget
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        class DummyMainWindow(QWidget):
            def __init__(self):
                super().__init__()
                self.refreshed = False
                self.populated = False
                self.tree_controller = self

            def refresh_tree(self):
                self.refreshed = True

            def populate_tree(self):
                self.populated = True

        parent = DummyMainWindow()
        widget = DataViewerWidget(parent)
        widget._refresh_explorer_tree()
        self.assertTrue(parent.refreshed)
        self.assertFalse(parent.populated)

    def test_data_viewer_detects_only_modified_columns_for_batch_save(self):
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        widget = DataViewerWidget()
        widget._curve_entries = [
            {
                "db_path": "a.db",
                "well_id": 1,
                "curve_id": 10,
                "well_name": "WellA",
                "curve_name": "GR",
                "label": "GR",
                "tooltip": "WellA/FolderA/GR",
                "folder_name": "FolderA",
                "folder_path": "FolderA",
                "depth": np.array([100.0, 101.0]),
                "data": np.array([10.0, 11.0]),
            },
            {
                "db_path": "a.db",
                "well_id": 1,
                "curve_id": 11,
                "well_name": "WellA",
                "curve_name": "RT",
                "label": "RT",
                "tooltip": "WellA/FolderA/RT",
                "folder_name": "FolderA",
                "folder_path": "FolderA",
                "depth": np.array([100.0, 101.0]),
                "data": np.array([20.0, 21.0]),
            },
        ]
        widget._rebuild_model()
        widget.model.setData(widget.model.index(0, 2), "15")

        modified = widget._build_modified_column_payloads()
        self.assertEqual(len(modified), 1)
        self.assertEqual(modified[0]["curve_name"], "GR")
        self.assertEqual(modified[0]["default_name"], "GR_edit")

    def test_data_viewer_batch_save_dialog_returns_selected_rows(self):
        from scripts.ui.widgets.data_viewer_widget import _BatchSaveCurvesDialog

        payloads = [
            {
                "column_index": 0,
                "curve_name": "GR",
                "default_name": "GR_edit",
                "well_name": "WellA",
                "folder_path": "FrameA",
            },
            {
                "column_index": 1,
                "curve_name": "RT",
                "default_name": "RT_edit",
                "well_name": "WellB",
                "folder_path": "FrameB",
            },
        ]
        dlg = _BatchSaveCurvesDialog(payloads=payloads)
        dlg._rows[1]["checkbox"].setChecked(False)
        values = dlg.values()
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]["target_name"], "GR_edit")

    def test_data_viewer_refreshes_baseline_for_saved_columns_only(self):
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        widget = DataViewerWidget()
        widget._curve_entries = [
            {
                "db_path": "a.db",
                "well_id": 1,
                "curve_id": 10,
                "well_name": "WellA",
                "curve_name": "GR",
                "label": "GR",
                "tooltip": "WellA/FolderA/GR",
                "folder_name": "FolderA",
                "folder_path": "FolderA",
                "depth": np.array([100.0, 101.0]),
                "data": np.array([10.0, 11.0]),
            },
            {
                "db_path": "a.db",
                "well_id": 1,
                "curve_id": 11,
                "well_name": "WellA",
                "curve_name": "RT",
                "label": "RT",
                "tooltip": "WellA/FolderA/RT",
                "folder_name": "FolderA",
                "folder_path": "FolderA",
                "depth": np.array([100.0, 101.0]),
                "data": np.array([20.0, 21.0]),
            },
        ]
        widget._rebuild_model()
        widget.model.setData(widget.model.index(0, 2), "15")
        widget.model.setData(widget.model.index(0, 3), "25")

        widget._refresh_baseline_for_columns([0])
        modified = widget._get_modified_column_indexes()
        self.assertEqual(modified, [1])

    def test_data_viewer_builds_save_arrays_on_source_depth_axis(self):
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        widget = DataViewerWidget()
        request = {
            "depth_values": np.array([100.0, 100.5, 101.0, 101.5], dtype=np.float32),
            "source_depth_values": np.array([100.5, 101.5], dtype=np.float32),
            "values": [1.0, 2.0, 3.0, 4.0],
        }

        save_depths, save_values = widget._build_curve_save_arrays(request)
        np.testing.assert_allclose(save_depths, np.array([100.5, 101.5], dtype=np.float32))
        np.testing.assert_allclose(save_values, np.array([2.0, 4.0], dtype=np.float32))

    def test_data_viewer_single_curve_save_arrays_keep_full_source_length(self):
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        widget = DataViewerWidget()
        request = {
            "depth_values": np.array([1000.0, 1000.5, 1001.0, 1001.5], dtype=np.float32),
            "source_depth_values": np.array([1000.0, 1000.5, 1001.0, 1001.5], dtype=np.float32),
            "values": [10.0, 11.0, 12.0, 13.0],
        }

        save_depths, save_values = widget._build_curve_save_arrays(request)
        self.assertEqual(len(save_depths), 4)
        self.assertEqual(len(save_values), 4)
        np.testing.assert_allclose(save_depths, request["source_depth_values"])
        np.testing.assert_allclose(save_values, np.array([10.0, 11.0, 12.0, 13.0], dtype=np.float32))

    def test_data_viewer_single_curve_preserves_duplicate_depth_rows(self):
        from PySide6.QtCore import Qt
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        widget = DataViewerWidget()
        widget._curve_entries = [
            {
                "db_path": "a.db",
                "well_id": 1,
                "curve_id": 10,
                "well_name": "WellA",
                "curve_name": "RT",
                "label": "RT",
                "tooltip": "WellA/FrameA/RT",
                "folder_name": "FrameA",
                "folder_path": "FrameA",
                "depth": np.array([100.0, 100.0, 100.5, 101.0], dtype=float),
                "data": np.array([1.0, 2.0, 3.0, 4.0], dtype=float),
            }
        ]

        widget._rebuild_model()

        self.assertEqual(widget.model.rowCount(), 4)
        self.assertEqual(widget.model.data(widget.model.index(0, 1), Qt.DisplayRole), "100.0000")
        self.assertEqual(widget.model.data(widget.model.index(1, 1), Qt.DisplayRole), "100.0000")
        self.assertEqual(widget.model.data(widget.model.index(0, 2), Qt.DisplayRole), "1.0000")
        self.assertEqual(widget.model.data(widget.model.index(1, 2), Qt.DisplayRole), "2.0000")

    def test_data_viewer_same_depth_curves_share_one_page_without_unique(self):
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        widget = DataViewerWidget()
        first = {
            "db_path": "a.db",
            "well_id": 1,
            "curve_id": 10,
            "well_name": "WellA",
            "curve_name": "RT",
            "unit": "ohm.m",
            "label": "RT",
            "tooltip": "WellA/FrameA/RT",
            "folder_path": "FrameA",
            "folder_name": "FrameA",
            "depth": np.array([100.0, 100.0, 100.5], dtype=float),
            "data": np.array([1.0, 2.0, 3.0], dtype=float),
        }
        second = {
            "db_path": "a.db",
            "well_id": 1,
            "curve_id": 11,
            "well_name": "WellA",
            "curve_name": "GR",
            "unit": "API",
            "label": "GR",
            "tooltip": "WellA/FrameA/GR",
            "folder_path": "FrameA",
            "folder_name": "FrameA",
            "depth": np.array([100.0, 100.0, 100.5], dtype=float),
            "data": np.array([4.0, 5.0, 6.0], dtype=float),
        }

        self.assertTrue(widget._append_loaded_entry(first, allow_redirect=False))
        self.assertTrue(widget._append_loaded_entry(second, allow_redirect=False))
        self.assertEqual(widget.model.rowCount(), 3)
        self.assertEqual(widget.model.columnCount(), 4)

    def test_data_viewer_same_folder_curves_share_page_before_depth_compare(self):
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        widget = DataViewerWidget()
        first = {
            "db_path": "a.db",
            "well_id": 1,
            "curve_id": 10,
            "well_name": "WellA",
            "curve_name": "RT",
            "unit": "ohm.m",
            "label": "RT",
            "tooltip": "WellA/FrameA/RT",
            "folder_path": "FrameA",
            "folder_name": "FrameA",
            "depth": np.array([100.0, 100.5, 101.0], dtype=float),
            "data": np.array([1.0, 2.0, 3.0], dtype=float),
        }
        second = {
            "db_path": "a.db",
            "well_id": 1,
            "curve_id": 11,
            "well_name": "WellA",
            "curve_name": "GR",
            "unit": "API",
            "label": "GR",
            "tooltip": "WellA/FrameA/GR",
            "folder_path": "FrameA",
            "folder_name": "FrameA",
            "depth": np.array([100.0, 100.6, 101.2], dtype=float),
            "data": np.array([4.0, 5.0, 6.0], dtype=float),
        }

        self.assertTrue(widget._append_loaded_entry(first, allow_redirect=False))
        self.assertTrue(widget._append_loaded_entry(second, allow_redirect=False))
        self.assertEqual(len(widget._curve_entries), 2)

    def test_data_viewer_same_folder_curve_saves_on_view_depth_axis(self):
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        widget = DataViewerWidget()
        widget._curve_entries = [
            {
                "db_path": "a.db",
                "well_id": 1,
                "curve_id": 10,
                "well_name": "WellA",
                "curve_name": "RT",
                "unit": "ohm.m",
                "label": "RT",
                "tooltip": "WellA/FrameA/RT",
                "folder_path": "FrameA",
                "folder_name": "FrameA",
                "depth": np.array([100.0, 100.5, 101.0], dtype=float),
                "data": np.array([1.0, 2.0, 3.0], dtype=float),
            },
            {
                "db_path": "a.db",
                "well_id": 1,
                "curve_id": 11,
                "well_name": "WellA",
                "curve_name": "GR",
                "unit": "API",
                "label": "GR",
                "tooltip": "WellA/FrameA/GR",
                "folder_path": "FrameA",
                "folder_name": "FrameA",
                "depth": np.array([100.0, 100.6, 101.2], dtype=float),
                "data": np.array([4.0, 5.0, 6.0], dtype=float),
            },
        ]
        widget._rebuild_model()
        widget.model.setData(widget.model.index(0, 3), "4.5")

        payloads = widget._build_modified_column_payloads()
        self.assertEqual(len(payloads), 1)
        self.assertTrue(payloads[0]["save_on_view_depth_axis"])
        save_depths, save_values = widget._build_curve_save_arrays(payloads[0])
        np.testing.assert_allclose(save_depths, np.array([100.0, 100.5, 101.0], dtype=np.float32))
        np.testing.assert_allclose(save_values, np.array([4.5, 5.0, 6.0], dtype=np.float32))

    def test_data_viewer_different_folder_same_depth_curves_share_page(self):
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        widget = DataViewerWidget()
        first = {
            "db_path": "a.db",
            "well_id": 1,
            "curve_id": 10,
            "well_name": "WellA",
            "curve_name": "RT",
            "unit": "ohm.m",
            "label": "RT",
            "tooltip": "WellA/FrameA/RT",
            "folder_path": "FrameA",
            "folder_name": "FrameA",
            "depth": np.array([100.0, 100.5, 101.0], dtype=float),
            "data": np.array([1.0, 2.0, 3.0], dtype=float),
        }
        second = {
            "db_path": "a.db",
            "well_id": 1,
            "curve_id": 11,
            "well_name": "WellA",
            "curve_name": "GR",
            "unit": "API",
            "label": "GR",
            "tooltip": "WellA/FrameB/GR",
            "folder_path": "FrameB",
            "folder_name": "FrameB",
            "depth": np.array([100.0, 100.5, 101.0], dtype=float),
            "data": np.array([4.0, 5.0, 6.0], dtype=float),
        }

        self.assertTrue(widget._append_loaded_entry(first, allow_redirect=False))
        self.assertTrue(widget._append_loaded_entry(second, allow_redirect=False))
        self.assertEqual(len(widget._curve_entries), 2)

    def test_data_viewer_different_depth_curve_redirects_to_new_page(self):
        from PySide6.QtWidgets import QWidget
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        class DummyStatusBar:
            def showMessage(self, message, timeout=0):
                return None

        class DummyMainWindow(QWidget):
            def __init__(self):
                super().__init__()
                self.created = []
                self._status = DummyStatusBar()

            def new_data_viewer_window(self):
                viewer = DataViewerWidget()
                self.created.append(viewer)
                return viewer

            def statusBar(self):
                return self._status

        parent = DummyMainWindow()
        widget = DataViewerWidget(parent)
        first = {
            "db_path": "a.db",
            "well_id": 1,
            "curve_id": 10,
            "well_name": "WellA",
            "curve_name": "RT",
            "unit": "ohm.m",
            "label": "RT",
            "tooltip": "WellA/FrameA/RT",
            "folder_path": "FrameA",
            "folder_name": "FrameA",
            "depth": np.array([100.0, 100.5, 101.0], dtype=float),
            "data": np.array([1.0, 2.0, 3.0], dtype=float),
        }
        second = {
            "db_path": "a.db",
            "well_id": 1,
            "curve_id": 11,
            "well_name": "WellA",
            "curve_name": "GR",
            "unit": "API",
            "label": "GR",
            "tooltip": "WellA/FrameB/GR",
            "folder_path": "FrameB",
            "folder_name": "FrameB",
            "depth": np.array([100.0, 100.6, 101.2], dtype=float),
            "data": np.array([4.0, 5.0, 6.0], dtype=float),
        }

        self.assertTrue(widget._append_loaded_entry(first, allow_redirect=False))
        self.assertFalse(widget._append_loaded_entry(second, allow_redirect=True))
        self.assertEqual(len(widget._curve_entries), 1)
        self.assertEqual(len(parent.created), 1)
        self.assertEqual(len(parent.created[0]._curve_entries), 1)

    def test_data_viewer_redirects_1d_curve_when_current_page_contains_2d(self):
        from PySide6.QtWidgets import QWidget
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        class DummyStatusBar:
            def showMessage(self, message, timeout=0):
                return None

        class DummyMainWindow(QWidget):
            def __init__(self):
                super().__init__()
                self.created = []
                self._status = DummyStatusBar()

            def new_data_viewer_window(self):
                viewer = DataViewerWidget()
                self.created.append(viewer)
                return viewer

            def statusBar(self):
                return self._status

        parent = DummyMainWindow()
        widget = DataViewerWidget(parent)
        first = {
            "db_path": "a.db",
            "well_id": 1,
            "curve_id": 10,
            "well_name": "WellA",
            "curve_name": "IMG",
            "unit": "",
            "label": "IMG",
            "tooltip": "WellA/FrameA/IMG",
            "folder_path": "FrameA",
            "folder_name": "FrameA",
            "depth": np.array([100.0, 100.5], dtype=float),
            "data": np.array([[1.0, 2.0], [3.0, 4.0]], dtype=float),
        }
        second = {
            "db_path": "a.db",
            "well_id": 1,
            "curve_id": 11,
            "well_name": "WellA",
            "curve_name": "RT",
            "unit": "ohm.m",
            "label": "RT",
            "tooltip": "WellA/FrameB/RT",
            "folder_path": "FrameB",
            "folder_name": "FrameB",
            "depth": np.array([100.0, 100.5], dtype=float),
            "data": np.array([4.0, 5.0], dtype=float),
        }

        self.assertTrue(widget._append_loaded_entry(first, allow_redirect=False))
        self.assertFalse(widget._append_loaded_entry(second, allow_redirect=True))
        self.assertEqual(len(widget._curve_entries), 1)
        self.assertEqual(len(parent.created), 1)
        self.assertEqual(len(parent.created[0]._curve_entries), 1)

    def test_data_viewer_find_folder_id_by_path_requires_existing_folder(self):
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "viewer_folder_lookup.db")
            db = DBManager(db_path)
            well_id = db.save_well("WellA")
            frame_id = db.create_folder(well_id, "FRAME1")
            db.create_folder(well_id, "SUB1", parent_id=frame_id)

            widget = DataViewerWidget()
            self.assertEqual(widget._find_folder_id_by_path(db, well_id, "FRAME1/SUB1"), db.get_folders(well_id)[1][0])
            self.assertIsNone(widget._find_folder_id_by_path(db, well_id, "FRAME1/MISSING"))

    def test_data_viewer_apply_saved_curve_result_refreshes_current_column_identity(self):
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        widget = DataViewerWidget()
        widget._curve_entries = [
            {
                "db_path": "a.db",
                "well_id": 1,
                "curve_id": 10,
                "well_name": "WellA",
                "curve_name": "RT",
                "unit": "ohm.m",
                "label": "RT",
                "tooltip": "WellA/FrameA/RT",
                "folder_path": "FrameA",
                "folder_name": "FrameA",
                "depth": np.array([100.0, 100.5], dtype=float),
                "data": np.array([1.0, 2.0], dtype=float),
            }
        ]
        widget._rebuild_model()

        widget._apply_saved_curve_result(
            {"column_index": 0},
            {
                "curve_id": 99,
                "curve_name": "RT_edit",
                "folder_path": "FrameA",
                "data": np.array([5.0, np.nan], dtype=float),
            },
        )

        self.assertEqual(widget._curve_entries[0]["curve_id"], 99)
        self.assertEqual(widget._curve_entries[0]["curve_name"], "RT_edit")
        self.assertEqual(widget._curve_entries[0]["tooltip"], "WellA/FrameA/RT_edit")
        self.assertEqual(widget.model.columns[0]["label"], "RT_edit")
        self.assertEqual(widget.model.columns[0]["tooltip"], "WellA/FrameA/RT_edit")
        self.assertEqual(widget.model.columns[0]["values"], [5.0, None])

    def test_data_viewer_widget_resolves_well_name_from_get_wells(self):
        from scripts.ui.widgets.data_viewer_widget import DataViewerWidget

        class DummyDb:
            def get_wells(self):
                return [(1, "WellA"), (2, "WellB")]

        self.assertEqual(DataViewerWidget._resolve_well_name(DummyDb(), 2), "WellB")
        self.assertEqual(DataViewerWidget._resolve_well_name(DummyDb(), 3), "Well 3")


class WorkspaceLaunchpadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_parse_curve_mime_payload_handles_multiple_curves(self):
        payload = "1:10:D:/data/A.db|2:20:D:/data/B.db"
        curves = parse_curve_mime_payload(payload)

        self.assertEqual(len(curves), 2)
        self.assertEqual(curves[0]["well_id"], 1)
        self.assertEqual(curves[0]["curve_id"], 10)
        self.assertEqual(curves[0]["db_path"], "D:/data/A.db")
        self.assertEqual(curves[1]["well_id"], 2)
        self.assertEqual(curves[1]["curve_id"], 20)

    def test_workspace_launch_tile_emits_click_signal(self):
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from scripts.ui.widgets.workspace_launchpad_widget import WorkspaceLaunchTile

        tile = WorkspaceLaunchTile("plot", "Plot")
        clicked = []
        tile.clicked.connect(clicked.append)

        event = QMouseEvent(
            QMouseEvent.MouseButtonRelease,
            QPointF(20, 20),
            QPointF(20, 20),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        tile.mouseReleaseEvent(event)

        self.assertEqual(clicked, ["plot"])

    def test_workspace_launchpad_registers_default_actions(self):
        from scripts.ui.widgets.workspace_launchpad_widget import WorkspaceLaunchpadWidget

        widget = WorkspaceLaunchpadWidget()
        self.assertIn("plot", widget._tiles)
        self.assertIn("data_viewer", widget._tiles)

    def test_main_window_shows_launchpad_only_when_workspace_is_empty(self):
        from main import MainWindow

        window = MainWindow(show_ai_chat=False, show_scripts=False)
        window._update_workspace_launchpad_visibility()
        self.assertFalse(window.workspace_launchpad.isHidden())

        plot = window.new_plot_window()
        self.assertIsNotNone(plot)
        window._update_workspace_launchpad_visibility()
        self.assertTrue(window.workspace_launchpad.isHidden())


class ScriptPreviewBehaviorTests(unittest.TestCase):
    class DummyPreviewBar:
        def __init__(self):
            self.visible = False

        def show(self):
            self.visible = True

        def hide(self):
            self.visible = False

        def isVisible(self):
            return self.visible

    class DummyAction:
        def __init__(self):
            self.enabled = False

        def setEnabled(self, enabled):
            self.enabled = bool(enabled)

    class DummyPage:
        def __init__(self):
            self.scripts = []

        def runJavaScript(self, script, *args):
            self.scripts.append(script)

    class DummyWebView:
        def __init__(self, page):
            self._page = page

        def page(self):
            return self._page

    class DummyBridge:
        def __init__(self, content):
            self._content = content

    class DummyOutput:
        def __init__(self):
            self.text = ""

        def setPlainText(self, text):
            self.text = text

    class DummySignal:
        def __init__(self):
            self.emitted = []

        def emit(self, *args):
            self.emitted.append(args)

    def _make_preview_editor(self, code="print('old')\n", script_path=None, page=None):
        from plugins.ai_assistant.ui.widgets.web_script_editor import WebScriptEditor

        editor = WebScriptEditor.__new__(WebScriptEditor)
        editor.editor_id = "editor-1"
        editor.script_path = script_path
        editor._preview_session = None
        editor._last_review_record = None
        editor.preview_bar = self.DummyPreviewBar()
        editor.review_action = self.DummyAction()
        editor.bridge = self.DummyBridge(code)
        editor.web_view = self.DummyWebView(page or self.DummyPage())
        editor.output = self.DummyOutput()
        editor.script_saved = self.DummySignal()
        editor.get_code = lambda: editor.bridge._content
        editor.window = lambda: None
        return editor

    def test_draft_review_session_state_exposes_base_and_draft_hashes(self):
        editor = self._make_preview_editor()

        payload = editor.start_preview_session("print('new')\n")
        state = editor.get_script_state()

        self.assertEqual(payload["base_code"], "print('old')\n")
        self.assertEqual(payload["draft_code"], "print('new')\n")
        self.assertTrue(state["is_preview_active"])
        self.assertIsNotNone(state["preview_session_id"])
        self.assertNotEqual(state["base_hash"], state["draft_hash"])
        self.assertFalse(editor.preview_bar.isVisible())
        self.assertFalse(editor.review_action.enabled)

    def test_reject_preview_restores_base_without_saving(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "demo.py")
            with open(filepath, "w", encoding="utf-8") as handle:
                handle.write("print('old')\n")
            editor = self._make_preview_editor("print('old')\n", script_path=filepath)
            editor.start_preview_session("print('new')\n")

            editor.reject_preview()

            self.assertFalse(editor.is_preview_active())
            self.assertEqual(editor.bridge._content, "print('old')\n")
            with open(filepath, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "print('old')\n")

    def test_js_preview_accept_callback_clears_and_auto_saves_draft(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "demo.py")
            with open(filepath, "w", encoding="utf-8") as handle:
                handle.write("print('old')\n")
            editor = self._make_preview_editor("print('old')\n", script_path=filepath)
            editor.save_code = lambda target: editor._perform_save(target, editor.bridge._content)
            editor.start_preview_session("print('new')\n")

            with patch("PySide6.QtCore.QTimer.singleShot", side_effect=lambda _ms, fn: fn()):
                editor._on_js_preview_accepted()

            self.assertFalse(editor.is_preview_active())
            self.assertIsNotNone(editor._last_review_record)
            self.assertTrue(editor.review_action.enabled)
            with open(filepath, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "print('new')\n")

    def test_consecutive_preview_keeps_first_base_code(self):
        editor = self._make_preview_editor("base\n")

        editor.start_preview_session("draft one\n")
        first_session = editor._preview_session.session_id
        editor.start_preview_session("draft two\n")

        self.assertNotEqual(editor._preview_session.session_id, first_session)
        self.assertEqual(editor._preview_session.base_code, "base\n")
        self.assertEqual(editor._preview_session.draft_code, "draft two\n")

    def test_editor_template_uses_silent_review_session_apis(self):
        template_path = os.path.join(
            PROJECT_ROOT,
            "plugins",
            "ai_assistant",
            "ui",
            "resources",
            "editor_template.html",
        )
        with open(template_path, "r", encoding="utf-8") as handle:
            template = handle.read()

        self.assertIn("window.startPreviewSession", template)
        self.assertIn("window.clearPreviewSession", template)
        self.assertIn("window.setContent(payload.draft_code", template)
        self.assertNotIn('id="preview-panel"', template)
        self.assertNotIn('data-preview-mode="original"', template)
        self.assertNotIn('data-preview-mode="diff"', template)
        self.assertNotIn('data-preview-mode="draft"', template)

    def test_agent_page_host_exposes_generic_dialog_interface(self):
        host_path = os.path.join(
            PROJECT_ROOT,
            "plugins",
            "ai_assistant",
            "ui",
            "widgets",
            "agent_page_host.py",
        )
        with open(host_path, "r", encoding="utf-8") as handle:
            host_code = handle.read()

        self.assertIn("class AgentPageBridge(QObject):", host_code)
        self.assertIn("class AgentPageDialog(ThemeDialog, _AgentPageHostMixin):", host_code)
        self.assertIn("class AgentPageWidget(QWidget, _AgentPageHostMixin):", host_code)
        self.assertIn('self.channel.registerObject("pageBridge", self.bridge)', host_code)
        self.assertIn("def open_agent_page(", host_code)
        self.assertIn('if mode == "dialog":', host_code)
        self.assertIn('if mode == "mdi":', host_code)
        self.assertIn("def _find_existing_mdi_page(main_window, page_id):", host_code)
        self.assertIn("def close_agent_page(page_id, parent=None):", host_code)
        self.assertIn("ThemeManager.get_web_theme_css(theme_name)", host_code)
        self.assertIn("if(window.setTheme) window.setTheme", host_code)

    def test_review_action_opens_generic_agent_page(self):
        editor_path = os.path.join(
            PROJECT_ROOT,
            "plugins",
            "ai_assistant",
            "ui",
            "widgets",
            "web_script_editor.py",
        )
        with open(editor_path, "r", encoding="utf-8") as handle:
            editor_code = handle.read()

        self.assertIn("from ..review_registry import open_review_page, register_review_record", editor_code)
        self.assertIn("register_review_record(payload)", editor_code)
        self.assertIn("open_review_page(self._last_review_record.script_path, parent=self, payload=payload)", editor_code)
        self.assertIn('self.review_action = QAction("Review", self)', editor_code)
        self.assertIn('self.setWindowTitle("AI Review")', editor_code)

    def test_tool_executor_exposes_agent_page_page_signals(self):
        executor_path = os.path.join(
            PROJECT_ROOT,
            "plugins",
            "ai_assistant",
            "tools",
            "tool_executor.py",
        )
        with open(executor_path, "r", encoding="utf-8") as handle:
            executor_code = handle.read()

        self.assertIn("execute_open_agent_page = Signal(object)", executor_code)
        self.assertIn("execute_update_agent_page = Signal(object)", executor_code)
        self.assertIn("execute_close_agent_page = Signal(object)", executor_code)
        self.assertIn("def _open_agent_page(self, payload):", executor_code)
        self.assertIn("def _update_agent_page(self, payload):", executor_code)
        self.assertIn("def _close_agent_page(self, payload):", executor_code)

    def test_agent_page_tools_are_registered_with_expected_names(self):
        self.assertEqual(OpenAgentPageTool().name, "tool_open_agent_page")
        self.assertEqual(UpdateAgentPageTool().name, "tool_update_agent_page")
        self.assertEqual(CloseAgentPageTool().name, "tool_close_agent_page")

    def test_tool_executor_preview_uses_start_preview_session_result(self):
        from plugins.ai_assistant.tools.tool_executor import ToolExecutor

        class DummyWidget:
            editor_id = "editor-1"
            script_path = "scripts_user/demo.py"

            def __init__(self):
                self.preview_calls = []

            def start_preview_session(self, code, source="ai_preview"):
                self.preview_calls.append((code, source))

        class DummySubWindow:
            def __init__(self, widget):
                self._widget = widget

            def widget(self):
                return self._widget

        class DummyMdiArea:
            def __init__(self, sub):
                self.sub = sub

            def subWindowList(self):
                return [self.sub]

            def setActiveSubWindow(self, _sub):
                return None

            def activeSubWindow(self):
                return self.sub

        class DummyMainWindow:
            def __init__(self, sub):
                self.mdi_area = DummyMdiArea(sub)

        widget = DummyWidget()
        executor = ToolExecutor.__new__(ToolExecutor)
        executor.main_window = DummyMainWindow(DummySubWindow(widget))
        executor._last_script_editor_id = None
        executor.tool_executed = self.DummySignal()

        executor._preview_script_code({"editor_id": "editor-1"}, "print('draft')")

        self.assertEqual(widget.preview_calls, [("print('draft')", "ai_preview")])
        result = json.loads(executor.tool_executed.emitted[0][0])
        self.assertTrue(result["ok"])
        self.assertEqual(result["editor_id"], "editor-1")

    def test_get_script_editor_code_prefers_exact_editor_id_over_active_tab(self):
        from plugins.ai_assistant.tools.file_tool import _get_script_editor_code

        class DummyWidget:
            def __init__(self, editor_id, script_path, code):
                self.editor_id = editor_id
                self.script_path = script_path
                self._code = code

            def get_code(self):
                return self._code

        class DummySub:
            def __init__(self, widget):
                self._widget = widget

            def widget(self):
                return self._widget

        class DummyMdiArea:
            def __init__(self, widgets):
                self._subs = [DummySub(widget) for widget in widgets]

            def subWindowList(self):
                return self._subs

        class DummyMainWindow:
            def __init__(self, widgets):
                self.mdi_area = DummyMdiArea(widgets)

        widgets = [
            DummyWidget("editor-active", "scripts_user/active.py", "active-code"),
            DummyWidget("editor-target", "scripts_user/target.py", "target-code"),
        ]
        main_window = DummyMainWindow(widgets)

        result = _get_script_editor_code(main_window, editor_id="editor-target")

        self.assertEqual(result, "target-code")

    def test_set_script_code_prefers_preview_for_existing_script_editor(self):
        tool = SetScriptCodeTool(main_window=object(), tool_executor=object())

        with patch("plugins.ai_assistant.tools.file_tool._preview_script_update") as mock_preview:
            mock_preview.return_value = {
                "ok": True,
                "previewed": True,
                "editor_id": "editor-1",
                "script_path": "scripts_user/demo.py",
                "message": "Preview mode activated",
            }
            result = tool.execute(code="print('hi')", editor_id="editor-1")

        self.assertTrue(result.get("ok"), result)
        self.assertTrue(result.get("previewed"), result)
        mock_preview.assert_called_once()

    def test_try_preview_change_uses_structured_preview_payload(self):
        from plugins.ai_assistant.tools.edit_file_tool import try_preview_change

        class DummySignal:
            def __init__(self):
                self._callbacks = []
                self.calls = []

            def connect(self, callback):
                self._callbacks.append(callback)

            def disconnect(self, callback):
                if callback in self._callbacks:
                    self._callbacks.remove(callback)

            def emit(self, *args):
                self.calls.append(args)
                for callback in list(self._callbacks):
                    callback(*args)

        class DummyExecutor:
            def __init__(self):
                self.tool_executed = DummySignal()
                self.execute_open_script_file = DummySignal()
                self.execute_preview_script_code = DummySignal()
                self.execute_open_script_file.connect(self._open)
                self.execute_preview_script_code.connect(self._preview)

            def _open(self, filepath):
                self.tool_executed.emit('{"ok": true, "editor_id": "editor-1", "filepath": "' + filepath.replace("\\", "\\\\") + '"}')

            def _preview(self, payload, _code):
                self.tool_executed.emit('{"ok": true, "message": "Preview shown in editor", "editor_id": "editor-1"}')

        class DummyLoop:
            def exec(self):
                return None

            def quit(self):
                return None

        with patch("plugins.ai_assistant.tools.edit_file_tool._attach_script_state", side_effect=lambda result, *_args, **_kwargs: result), patch(
            "PySide6.QtCore.QEventLoop",
            DummyLoop,
        ), patch(
            "PySide6.QtCore.QTimer.singleShot",
            side_effect=lambda _ms, fn: fn(),
        ):
            executor = DummyExecutor()
            result = try_preview_change("scripts_user/demo.py", "print('x')", executor)

        self.assertTrue(result.get("previewed"), result)
        preview_payload, preview_code = executor.execute_preview_script_code.calls[0]
        self.assertEqual(preview_payload["editor_id"], "editor-1")
        self.assertEqual(preview_payload["script_path"], "scripts_user/demo.py")
        self.assertEqual(preview_code, "print('x')")

    def test_apply_patch_prefers_preview_for_python_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "demo.py")
            with open(filepath, "w", encoding="utf-8") as handle:
                handle.write("print('old')\n")

            tool = ApplyPatchTool(main_window=object(), tool_executor=object())
            with patch("plugins.ai_assistant.tools.patch_tool._preview_script_patch") as mock_preview:
                mock_preview.return_value = {
                    "ok": True,
                    "previewed": True,
                    "editor_id": "editor-1",
                    "script_path": filepath,
                }
                result = tool.execute(
                    filepath=filepath,
                    hunks=[{"old_string": "old", "new_string": "new"}],
                )

            self.assertTrue(result.get("ok"), result)
            self.assertTrue(result.get("previewed"), result)
            with open(filepath, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "print('old')\n")
            mock_preview.assert_called_once()

    def test_apply_patch_writes_through_file_editor_when_preview_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "demo.py")
            with open(filepath, "w", encoding="utf-8") as handle:
                handle.write("print('old')\n")

            tool = ApplyPatchTool()
            result = tool.execute(
                filepath=filepath,
                hunks=[{"old_string": "old", "new_string": "new"}],
            )

            self.assertTrue(result.get("ok"), result)
            self.assertEqual(result.get("applied_hunks"), 1)
            with open(filepath, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "print('new')\n")

    def test_preview_script_patch_uses_structured_preview_payload(self):
        from plugins.ai_assistant.tools.patch_tool import _preview_script_patch

        class DummySignal:
            def __init__(self):
                self._callbacks = []
                self.calls = []

            def connect(self, callback):
                self._callbacks.append(callback)

            def disconnect(self, callback):
                if callback in self._callbacks:
                    self._callbacks.remove(callback)

            def emit(self, *args):
                self.calls.append(args)
                for callback in list(self._callbacks):
                    callback(*args)

        class DummyExecutor:
            def __init__(self):
                self.tool_executed = DummySignal()
                self.execute_get_script_state = DummySignal()
                self.execute_preview_script_code = DummySignal()
                self.execute_get_script_state.connect(self._state)
                self.execute_preview_script_code.connect(self._preview)

            def _state(self, _payload):
                self.tool_executed.emit('{"ok": true, "editor_id": "editor-1", "script_path": "scripts_user/demo.py"}')

            def _preview(self, payload, _code):
                self.tool_executed.emit('{"ok": true, "message": "Preview shown in editor"}')

        class DummyLoop:
            def exec(self):
                return None

            def quit(self):
                return None

        executor = DummyExecutor()
        with patch("plugins.ai_assistant.tools.patch_tool.QEventLoop", DummyLoop):
            result = _preview_script_patch(executor, "scripts_user/demo.py", "print('x')")

        self.assertTrue(result.get("previewed"), result)
        preview_payload, preview_code = executor.execute_preview_script_code.calls[0]
        self.assertEqual(preview_payload["editor_id"], "editor-1")
        self.assertEqual(preview_payload["script_path"], "scripts_user/demo.py")
        self.assertEqual(preview_code, "print('x')")

    def test_insert_into_file_preview_result_includes_script_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "demo.py")
            with open(filepath, "w", encoding="utf-8") as handle:
                handle.write("print('old')\n")

            tool = InsertIntoFileTool(main_window=object(), tool_executor=object())
            with patch("plugins.ai_assistant.tools.edit_file_tool.try_preview_change") as mock_preview, patch(
                "plugins.ai_assistant.tools.edit_file_tool._attach_script_state",
                side_effect=lambda result, *_args, **_kwargs: result,
            ):
                mock_preview.return_value = {
                    "ok": True,
                    "previewed": True,
                    "editor_id": "editor-1",
                    "script_path": filepath,
                    "script_state": {
                        "editor_id": "editor-1",
                        "script_path": filepath,
                        "is_preview_active": True,
                        "has_unsaved_changes": True,
                    },
                }
                result = tool.execute(
                    filepath=filepath,
                    content="# inserted\n",
                    line_number=1,
                )

            self.assertTrue(result.get("ok"), result)
            self.assertTrue(result.get("previewed"), result)
            self.assertEqual(result.get("script_path"), filepath)

    def test_attach_script_state_adds_structured_preview_metadata(self):
        from plugins.ai_assistant.tools.edit_file_tool import _attach_script_state

        with patch("plugins.ai_assistant.tools.edit_file_tool._fetch_script_state") as mock_state:
            mock_state.return_value = {
                "ok": True,
                "editor_id": "editor-1",
                "script_path": "scripts_user/demo.py",
                "is_preview_active": True,
                "has_unsaved_changes": True,
                "preview_source": "ai",
                "should_run_from": "preview",
                "should_save_to": "scripts_user/demo.py",
            }
            result = _attach_script_state(
                {"ok": True, "previewed": True},
                tool_executor=object(),
                script_path="scripts_user/demo.py",
            )

            self.assertIn("script_state", result)
            self.assertEqual(result.get("editor_id"), "editor-1")
            self.assertTrue(result["script_state"].get("is_preview_active"))


class PlotDisplayRangeTests(unittest.TestCase):
    def test_schedule_plot_finalize_uses_qtimer(self):
        from scripts.utils.plot_finalize_utils import schedule_plot_finalize

        class DummyMainWindow:
            def show(self):
                return None

            def raise_(self):
                return None

        class DummySubWindow:
            def show(self):
                return None

        class DummyLogPlot:
            def set_vertical_scale(self, _scale):
                return None

            scroll_mgr = None

        with patch("scripts.utils.plot_finalize_utils.QTimer.singleShot") as mock_single_shot:
            schedule_plot_finalize(DummyMainWindow(), DummyLogPlot(), DummySubWindow())

        mock_single_shot.assert_called_once()
        self.assertEqual(mock_single_shot.call_args.args[0], 200)

    def test_get_or_create_plot_window_reuses_existing_titled_window(self):
        from scripts.utils.plot_window_utils import get_or_create_plot_window

        class DummySignal:
            def connect(self, _callback):
                return None

        class DummyLogWidget:
            def __init__(self):
                self.selectionChanged = DummySignal()

        class DummySubWindow:
            def __init__(self, title, widget):
                self._title = title
                self._widget = widget

            def windowTitle(self):
                return self._title

            def widget(self):
                return self._widget

        class DummyMdiArea:
            def __init__(self, subs):
                self._subs = subs

            def subWindowList(self):
                return self._subs

            def addSubWindow(self, _sub):
                raise AssertionError("should not create a new subwindow when one already exists")

        class DummyMainWindow:
            def __init__(self, sub):
                self.mdi_area = DummyMdiArea([sub])

            def setWindowTitle(self, _title):
                return None

        existing_plot = DummyLogWidget()
        existing_sub = DummySubWindow("Existing Plot", existing_plot)
        existing_main = DummyMainWindow(existing_sub)
        dummy_app = type(
            "DummyApp",
            (),
            {
                "setStyle": lambda self, _style: None,
                "topLevelWidgets": lambda self: [existing_main],
            },
        )()

        with patch("scripts.utils.plot_window_utils.QApplication.instance", return_value=dummy_app), patch(
            "scripts.utils.plot_window_utils.LogWidget",
            DummyLogWidget,
        ):
            app, mw, log_plot, target_sub = get_or_create_plot_window("Existing Plot")

        self.assertIs(app, dummy_app)
        self.assertIs(mw, existing_main)
        self.assertIs(log_plot, existing_plot)
        self.assertIs(target_sub, existing_sub)

    def test_ensure_track_container_reuses_existing_named_track(self):
        from scripts.utils.plot_track_utils import ensure_track_container

        class DummyTrack:
            def __init__(self, name):
                self.track_name = name
                self._api_track_id = None
                self.is_accum_fill = False
                self.plot_widget = object()

        class DummyLogPlot:
            def __init__(self, tracks):
                self.track_containers = tracks

        existing = DummyTrack("Track-A")
        log_plot = DummyLogPlot([existing])
        track_map = {}

        result = ensure_track_container(
            log_plot,
            track_map,
            track_id="Track-A",
            accum_fill=True,
            is_image=False,
        )

        self.assertIs(result, existing)
        self.assertTrue(existing.is_accum_fill)
        self.assertIs(track_map["Track-A"], existing)

    def test_ensure_track_container_does_not_reuse_anonymous_tracks(self):
        from scripts.utils.plot_track_utils import ensure_track_container

        class DummyInteractivePlotWidget:
            pass

        class DummyTrack:
            def __init__(self, name):
                self.track_name = name
                self._api_track_id = None
                self.is_accum_fill = False
                self.plot_widget = DummyInteractivePlotWidget()

        class DummyLogPlot:
            def __init__(self):
                self.track_containers = []

            def _add_track_to_layout(self, container, width=204):
                self.track_containers.append(container)

        class DummyCurveTrackContainer(DummyTrack):
            def __init__(self, _log_plot):
                super().__init__(name="")

        log_plot = DummyLogPlot()
        track_map = {}

        with patch("scripts.tracks.track_container.CurveTrackContainer", DummyCurveTrackContainer), patch(
            "scripts.tracks.track_container.ImageTrackContainer",
            DummyCurveTrackContainer,
        ), patch(
            "scripts.tracks.track_container.AccumulativeTrackContainer",
            DummyCurveTrackContainer,
        ), patch(
            "scripts.rendering.plot_components.InteractivePlotWidget",
            DummyInteractivePlotWidget,
        ):
            first = ensure_track_container(
                log_plot,
                track_map,
                track_id=None,
                accum_fill=False,
                is_image=False,
            )
            second = ensure_track_container(
                log_plot,
                track_map,
                track_id=None,
                accum_fill=False,
                is_image=False,
            )

        self.assertIsNot(first, second)
        self.assertEqual(len(log_plot.track_containers), 2)
        self.assertEqual(track_map, {})

    def test_prepare_curve_payload_aligns_lengths_and_defaults_fill_color(self):
        from scripts.utils.plot_payload_utils import prepare_curve_payload_for_render
        from scripts.utils.plot_style_utils import resolve_auto_fill_color

        prepared = prepare_curve_payload_for_render(
            {
                "name": "GR",
                "values": [1.0, 2.0, 3.0],
                "depth": [100.0, 101.0],
                "color": "#112233",
            },
            0,
            accum_fill=True,
        )

        self.assertEqual(len(prepared["values"]), 2)
        self.assertEqual(len(prepared["depth"]), 2)
        self.assertEqual(prepared["info"]["fill_mode"], "None")
        self.assertEqual(prepared["info"]["fill_color"], resolve_auto_fill_color("#112233", 1.0))

    def test_prepare_curve_payload_preserves_explicit_image_log_range_handling(self):
        from scripts.utils.plot_payload_utils import prepare_curve_payload_for_render

        prepared = prepare_curve_payload_for_render(
            {
                "name": "IMG",
                "values": [[float("nan"), -9999, 10.0], [-999.25, 20.0, 30.0]],
                "depth": [100.0, 101.0],
                "is_image": True,
                "log": True,
            },
            0,
        )

        self.assertTrue(prepared["is_image"])
        self.assertTrue(prepared["info"]["log"])
        self.assertEqual(prepared["info"]["min"], 10.0)
        self.assertEqual(prepared["info"]["max"], 30.0)

    def test_prepare_curve_payload_defaults_image_to_linear_when_unspecified(self):
        from scripts.utils.plot_payload_utils import prepare_curve_payload_for_render

        prepared = prepare_curve_payload_for_render(
            {
                "name": "IMG",
                "values": [[float("nan"), -9999, 10.0], [-999.25, 20.0, 30.0]],
                "depth": [100.0, 101.0],
                "is_image": True,
            },
            0,
        )

        self.assertTrue(prepared["is_image"])
        self.assertFalse(prepared["info"]["log"])
        self.assertEqual(prepared["info"]["min"], 10.0)
        self.assertEqual(prepared["info"]["max"], 30.0)

    def test_shared_curve_resolution_supports_folder_path_lookup(self):
        from scripts.utils.curve_resolution import resolve_curve_row

        curves = [
            (1, "GR", "gAPI", "100", 10),
            (2, "RT", "ohm.m", "100", 11),
        ]
        folder_map = {10: "FRAME0", 11: "FRAME1"}

        resolved = resolve_curve_row("FRAME0/GR", curves, folder_map)

        self.assertTrue(resolved.get("ok"), resolved)
        self.assertEqual(resolved["row"][0], 1)

    def test_shared_curve_resolution_reports_ambiguous_simple_name(self):
        from scripts.utils.curve_resolution import resolve_curve_row

        curves = [
            (1, "GR", "gAPI", "100", 10),
            (2, "GR", "gAPI", "100", 11),
        ]
        folder_map = {10: "FRAME0", 11: "FRAME1"}

        resolved = resolve_curve_row("GR", curves, folder_map)

        self.assertFalse(resolved.get("ok"))
        self.assertEqual(resolved.get("error_code"), "curve_ambiguous")
        self.assertIn("FRAME0/GR", resolved.get("suggestions", []))

    def test_plot_style_defaults_resistivity_curve_to_log(self):
        from scripts.utils.plot_style_utils import normalize_curve_plot_style

        info = normalize_curve_plot_style({"unit": "ohm.m", "is_image": False})

        self.assertTrue(info["log"])

    def test_plot_style_defaults_image_curve_to_linear_even_with_resistivity_unit(self):
        from scripts.utils.plot_style_utils import normalize_curve_plot_style

        info = normalize_curve_plot_style({"unit": "ohm.m", "is_image": True})

        self.assertFalse(info["log"])

    def test_plot_style_preserves_explicit_image_log_flag(self):
        from scripts.utils.plot_style_utils import normalize_curve_plot_style

        info = normalize_curve_plot_style({"unit": "kohm", "is_image": True, "log": True})

        self.assertTrue(info["log"])

    def test_plot_null_constants_share_single_source_of_truth(self):
        from scripts.rendering.plot_constants import NULL_MNEMONICS
        from scripts.utils.plot_value_utils import INVALID_VALUE_SENTINELS

        self.assertEqual(tuple(NULL_MNEMONICS), INVALID_VALUE_SENTINELS)

    def test_scalar_invalid_value_check_matches_plotting_rules(self):
        from scripts.utils.plot_value_utils import is_invalid_plot_value

        self.assertTrue(is_invalid_plot_value(float("nan")))
        self.assertTrue(is_invalid_plot_value(-999.25))
        self.assertTrue(is_invalid_plot_value(-9999))
        self.assertFalse(is_invalid_plot_value(12.34))

    def test_sanitize_invalid_plot_values_replaces_null_sentinels_with_nan(self):
        from scripts.utils.plot_value_utils import sanitize_invalid_plot_values

        values = [1.0, -9999.0, -999.25, 5.0]
        sanitized = sanitize_invalid_plot_values(values)

        self.assertEqual(float(sanitized[0]), 1.0)
        self.assertTrue(math.isnan(float(sanitized[1])))
        self.assertTrue(math.isnan(float(sanitized[2])))
        self.assertEqual(float(sanitized[3]), 5.0)

    def test_shared_helper_excludes_nan_and_null_sentinels(self):
        from scripts.utils.plot_value_utils import compute_auto_display_range

        values = [
            [float("nan"), -9999, 10.0],
            [-999.25, 20.0, 30.0],
        ]

        d_min, d_max = compute_auto_display_range(values, is_image=True, is_log=False)

        self.assertTrue(math.isfinite(d_min))
        self.assertTrue(math.isfinite(d_max))
        self.assertEqual(d_min, 10.0)
        self.assertEqual(d_max, 30.0)

    def test_image_auto_display_range_excludes_nan_and_null_sentinels(self):
        from pylog_api.legacy_impl import _compute_auto_display_range

        values = [
            [float("nan"), -9999, 10.0],
            [-999.25, 20.0, 30.0],
        ]

        d_min, d_max = _compute_auto_display_range(values, is_image=True, is_log=False)

        self.assertTrue(math.isfinite(d_min))
        self.assertTrue(math.isfinite(d_max))
        self.assertEqual(d_min, 10.0)
        self.assertEqual(d_max, 30.0)


class RunPythonFileBehaviorTests(unittest.TestCase):
    def test_run_detached_command_sets_utf8_python_env(self):
        from plugins.ai_assistant.tools.verify_tool import _run_detached_command

        with patch("plugins.ai_assistant.tools.verify_tool.NamedTemporaryFile") as mock_temp, patch(
            "plugins.ai_assistant.tools.verify_tool.open"
        ) as mock_open, patch("plugins.ai_assistant.tools.verify_tool.subprocess.Popen") as mock_popen:
            mock_temp.side_effect = [
                type("Tmp", (), {"name": "stdout.log", "close": lambda self: None})(),
                type("Tmp", (), {"name": "stderr.err", "close": lambda self: None})(),
            ]
            mock_handle = type("Handle", (), {"close": lambda self: None})()
            mock_open.return_value = mock_handle
            mock_popen.return_value = type("Proc", (), {"pid": 1234})()

            result = _run_detached_command(["python", "demo.py"], cwd="D:\\demo")

        self.assertTrue(result.get("ok"), result)
        kwargs = mock_popen.call_args.kwargs
        self.assertEqual(kwargs["env"]["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(kwargs["env"]["PYTHONUTF8"], "1")

    def test_select_background_python_executable_prefers_pythonw_on_windows(self):
        from plugins.ai_assistant.tools.verify_tool import _select_background_python_executable

        with patch("plugins.ai_assistant.tools.verify_tool.os.name", "nt"), patch(
            "plugins.ai_assistant.tools.verify_tool.sys.executable",
            r"C:\Python311\python.exe",
        ), patch("tools.verify_tool.Path.exists", return_value=True):
            result = _select_background_python_executable()

        self.assertTrue(result.lower().endswith("pythonw.exe"))

    def test_run_python_file_launches_interactive_plot_script_in_background(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "plot_demo.py")
            with open(filepath, "w", encoding="utf-8") as handle:
                handle.write(
                    "import matplotlib.pyplot as plt\n"
                    "plt.plot([1, 2], [3, 4])\n"
                    "plt.show()\n"
                )

            tool = RunPythonFileTool()
            with patch("plugins.ai_assistant.tools.verify_tool._run_detached_command") as mock_detached, patch(
                "plugins.ai_assistant.tools.verify_tool._select_background_python_executable",
                return_value="C:\\Python311\\pythonw.exe",
            ) as mock_select, patch(
                "plugins.ai_assistant.tools.verify_tool._run_command"
            ) as mock_run:
                mock_detached.return_value = {
                    "ok": True,
                    "background": True,
                    "pid": 1234,
                    "summary": "bg",
                    "stdout_log": "C:\\temp\\plot.log",
                    "stderr_log": "C:\\temp\\plot.err",
                }
                result = tool.execute(filepath=filepath)

            self.assertTrue(result.get("ok"), result)
            self.assertTrue(result.get("background"), result)
            self.assertEqual(result.get("strategy"), "background_execution")
            self.assertEqual(result.get("python_executable"), "C:\\Python311\\pythonw.exe")
            self.assertEqual(result.get("recommended_next_tool"), "tool_read_file")
            self.assertIn("stdout log", result.get("summary", ""))
            self.assertIn("stderr log", result.get("summary", ""))
            mock_select.assert_called_once()
            mock_detached.assert_called_once()
            mock_run.assert_not_called()

    def test_run_python_file_keeps_sync_mode_for_normal_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "normal_demo.py")
            with open(filepath, "w", encoding="utf-8") as handle:
                handle.write("print('hello')\n")

            tool = RunPythonFileTool()
            with patch("plugins.ai_assistant.tools.verify_tool._run_command") as mock_run, patch(
                "plugins.ai_assistant.tools.verify_tool._run_detached_command"
            ) as mock_detached:
                mock_run.return_value = {"ok": True, "summary": "Command succeeded"}
                result = tool.execute(filepath=filepath)

            self.assertTrue(result.get("ok"), result)
            mock_run.assert_called_once()
            mock_detached.assert_not_called()


if __name__ == "__main__":
    unittest.main()
