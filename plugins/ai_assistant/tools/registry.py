import importlib
import inspect
import os

try:
    from .base_tool import BaseTool
except ImportError:
    try:
        from plugins.ai_assistant.tools.base_tool import BaseTool
    except ImportError:
        import sys

        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        BaseTool = importlib.import_module("base_tool").BaseTool


class ToolRegistry:
    """Registry used to discover and instantiate AI tools."""

    def __init__(self):
        self.tools = []
        self._discovered = False

    def register(self, tool_class):
        """Register a tool class once."""
        if not self._is_tool_class(tool_class):
            raise TypeError(f"Tool class must inherit from BaseTool, got {tool_class.__name__}")

        if tool_class not in self.tools:
            self.tools.append(tool_class)
        return tool_class

    def discover(self, directory):
        """Discover tool modules and register BaseTool subclasses."""
        if self._discovered:
            return

        abs_directory = os.path.abspath(directory)
        package_prefix = __package__

        for _root, _dirs, files in os.walk(abs_directory):
            for file in files:
                if not file.endswith(".py") or file.startswith("_"):
                    continue

                module_name = os.path.splitext(file)[0]

                try:
                    import sys

                    if abs_directory not in sys.path:
                        sys.path.insert(0, abs_directory)

                    module = None
                    if package_prefix:
                        try:
                            module = importlib.import_module(f"{package_prefix}.{module_name}")
                        except Exception:
                            module = None

                    if module is None:
                        module = importlib.import_module(module_name)

                    for _name, obj in inspect.getmembers(module):
                        if (
                            inspect.isclass(obj)
                            and self._is_tool_class(obj)
                            and obj != BaseTool
                            and not getattr(obj, "is_abstract", False)
                        ):
                            self.register(obj)
                except Exception:
                    pass

        self._discovered = True

    def get_all_tools(self, main_window=None, tool_executor=None, ui_bridge=None, agent_state=None, execution_policy=None):
        """Instantiate all registered tools with supported dependencies."""
        tool_instances = []
        for tool_class in self.tools:
            sig = inspect.signature(tool_class.__init__)
            params = {}

            if "main_window" in sig.parameters:
                params["main_window"] = main_window
            if "tool_executor" in sig.parameters:
                params["tool_executor"] = tool_executor
            if "ui_bridge" in sig.parameters:
                params["ui_bridge"] = ui_bridge
            if "agent_state" in sig.parameters:
                params["agent_state"] = agent_state
            if "execution_policy" in sig.parameters:
                params["execution_policy"] = execution_policy

            try:
                tool_instances.append(tool_class(**params))
            except Exception as e:
                print(f"Error creating tool {tool_class.__name__}: {e}")

        return tool_instances

    def get_tool_specs(self, main_window=None, tool_executor=None, ui_bridge=None, agent_state=None, execution_policy=None):
        """Instantiate tools and return their standardized specs."""
        specs = []
        for tool in self.get_all_tools(
            main_window=main_window,
            tool_executor=tool_executor,
            ui_bridge=ui_bridge,
            agent_state=agent_state,
            execution_policy=execution_policy,
        ):
            try:
                specs.append(tool.spec)
            except Exception:
                pass
        return specs

    @staticmethod
    def _is_tool_class(obj):
        try:
            if issubclass(obj, BaseTool):
                return True
        except Exception:
            pass

        for base in getattr(obj, "__mro__", ())[1:]:
            if getattr(base, "__name__", "") == "BaseTool":
                return True
        return False


tool_registry = ToolRegistry()


def register_tool(tool_class):
    """Decorator used by tool modules to register tool classes."""
    return tool_registry.register(tool_class)
