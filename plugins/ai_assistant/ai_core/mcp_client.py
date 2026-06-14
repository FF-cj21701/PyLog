import asyncio
import os
from typing import Dict, List, Optional, Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from .tool_result import error_tool_result, normalize_tool_result

# Use absolute import within the plugin context
from ..tools.base_tool import BaseTool

class MCPToolWrapper(BaseTool):
    """Bridge for external MCP tools into PyLog's tool system."""
    
    def __init__(self, mcp_name: str, session: ClientSession, mcp_tool_info: Any, server_name: Optional[str] = None):
        # We need to map MCP tool info to BaseTool expected format
        description = mcp_tool_info.description or ""
        args_schema, required_args = self._extract_args_schema(mcp_tool_info)
        metadata = self._extract_metadata(mcp_name, mcp_tool_info, required_args, server_name=server_name)

        super().__init__(
            name=f"mcp_{mcp_name}", 
            description=f"[MCP] {description}", 
            args_schema=args_schema,
            metadata=metadata,
        )
        self.session = session
        self.original_name = mcp_name
        self.server_name = server_name

    async def execute(self, **kwargs):
        """Execute the MCP tool via the provided session."""
        try:
            # MCP call_tool expects tool name and arguments
            result = await self.session.call_tool(self.original_name, kwargs)

            content_blocks = []
            if hasattr(result, "content") and result.content:
                for block in result.content:
                    if hasattr(block, "text") and block.text is not None:
                        content_blocks.append(block.text)
                    else:
                        content_blocks.append(str(block))

            payload = {
                "tool_name": f"mcp_{self.original_name}",
                "source": "mcp",
                "content_blocks": content_blocks,
                "data": "\n".join(content_blocks) if content_blocks else str(result),
                "summary": "\n".join(content_blocks)[:4000] if content_blocks else f"MCP tool {self.original_name} completed",
            }
            return normalize_tool_result(f"mcp_{self.original_name}", payload, source="mcp")
        except Exception as e:
            return error_tool_result(f"mcp_{self.original_name}", f"MCP Tool execution failed: {str(e)}", source="mcp")

    @staticmethod
    def _extract_args_schema(mcp_tool_info: Any):
        input_schema = getattr(mcp_tool_info, "inputSchema", None) or {}
        required_args = []
        args_schema = input_schema
        if isinstance(input_schema, dict):
            required_args = list(input_schema.get("required") or [])
            if "properties" in input_schema and isinstance(input_schema["properties"], dict):
                args_schema = input_schema["properties"]
        if not isinstance(args_schema, dict):
            args_schema = {}
        return args_schema, [str(name) for name in required_args if str(name).strip()]

    @classmethod
    def _extract_metadata(cls, mcp_name: str, mcp_tool_info: Any, required_args: List[str], server_name: Optional[str] = None):
        annotations = getattr(mcp_tool_info, "annotations", None)
        title = getattr(mcp_tool_info, "title", None) or getattr(annotations, "title", None)
        read_only = cls._read_annotation_flag(annotations, "readOnlyHint", default=False)
        destructive = cls._read_annotation_flag(annotations, "destructiveHint", default=False)
        open_world = cls._read_annotation_flag(annotations, "openWorldHint", default=False)
        idempotent = cls._read_annotation_flag(annotations, "idempotentHint", default=False)

        side_effect_level = "none" if read_only else "write" if destructive else "execution" if open_world else "data_mutation"
        risk_level = "high" if destructive else "medium" if open_world else "low"
        output_type = "structured_data"
        capability_tags = ["mcp", "external_tool"]
        if read_only:
            capability_tags.append("read")
            capability_tags.append("read_only")
        if destructive:
            capability_tags.append("destructive")
        if open_world:
            capability_tags.append("open_world")
        if idempotent:
            capability_tags.append("idempotent")

        usage_bits = []
        if read_only:
            usage_bits.append("Prefer for external read/query operations.")
        if destructive:
            usage_bits.append("May mutate external state; call only when necessary.")
        elif open_world:
            usage_bits.append("May interact with external systems or environments.")

        return {
            "source": "mcp",
            "display_name": title,
            "server_name": server_name,
            "required_args": required_args,
            "side_effect_level": side_effect_level,
            "risk_level": risk_level,
            "output_type": output_type,
            "capability_tags": capability_tags,
            "domain_tags": ["external"],
            "usage_hint": " ".join(usage_bits),
            "mcp_original_name": mcp_name,
            "mcp_annotations": cls._annotation_dict(annotations),
        }

    @staticmethod
    def _read_annotation_flag(annotations: Any, name: str, default: bool = False) -> bool:
        if annotations is None:
            return default
        if isinstance(annotations, dict):
            return bool(annotations.get(name, default))
        return bool(getattr(annotations, name, default))

    @staticmethod
    def _annotation_dict(annotations: Any) -> Dict[str, Any]:
        if annotations is None:
            return {}
        if isinstance(annotations, dict):
            return dict(annotations)
        result = {}
        for key in ("title", "readOnlyHint", "destructiveHint", "openWorldHint", "idempotentHint"):
            value = getattr(annotations, key, None)
            if value is not None:
                result[key] = value
        return result


class MCPClientSession:
    """Manages a single connection to an MCP server."""
    
    def __init__(self, name: str, command: str, args: List[str] = None, env: Dict[str, str] = None):
        self.name = name
        self.command = str(command or "").strip()
        self.args = [str(arg) for arg in (args or [])]
        self.env = env or os.environ.copy()
        
        self.session: Optional[ClientSession] = None
        self._exit_stack = None
        self._is_connected = False
        self._lock = asyncio.Lock()

    async def connect(self):
        """Connect to the MCP server via stdio."""
        async with self._lock:
            if self._is_connected and self.session:
                return True

            if self._exit_stack and not self._is_connected:
                try:
                    await self._exit_stack.aclose()
                except Exception:
                    pass
                finally:
                    self._exit_stack = None
                    self.session = None

            server_params = StdioServerParameters(
                command=self.command,
                args=self.args,
                env=self.env
            )

            from contextlib import AsyncExitStack
            exit_stack = AsyncExitStack()
            self._exit_stack = exit_stack

            try:
                read, write = await exit_stack.enter_async_context(stdio_client(server_params))
                session = await exit_stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
            except asyncio.CancelledError:
                try:
                    await exit_stack.aclose()
                except Exception:
                    pass
                finally:
                    if self._exit_stack is exit_stack:
                        self._exit_stack = None
                    self.session = None
                    self._is_connected = False
                raise
            except BaseException as e:
                try:
                    await exit_stack.aclose()
                except Exception:
                    pass
                finally:
                    if self._exit_stack is exit_stack:
                        self._exit_stack = None
                    self.session = None
                    self._is_connected = False
                print(
                    f"Failed to connect to MCP server {self.name}: {e} "
                    f"(command={self.command!r}, args={self.args!r})"
                )
                return False

            self.session = session
            self._is_connected = True
            print(f"MCP connected to server: {self.name}")
            return True

    async def list_tools(self) -> List[MCPToolWrapper]:
        """Fetch tools from the server and wrap them."""
        if not self._is_connected or not self.session:
            return []
            
        try:
            response = await self.session.list_tools()
            tools = []
            for tool in response.tools:
                tools.append(MCPToolWrapper(tool.name, self.session, tool, server_name=self.name))
            return tools
        except Exception as e:
            print(f"Error listing tools for {self.name}: {e}")
            return []

    async def disconnect(self):
        """Safely disconnect from the server."""
        async with self._lock:
            exit_stack = self._exit_stack
            self._exit_stack = None
            self._is_connected = False
            self.session = None
            if exit_stack:
                await exit_stack.aclose()


class MCPClientManager:
    """Manages multiple MCP server sessions."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MCPClientManager, cls).__new__(cls)
            cls._instance.sessions = {}
        return cls._instance

    async def get_all_tools(self, server_configs: Dict[str, Any]) -> List[BaseTool]:
        """Initialize all configured servers and return their tools."""
        all_tools = []
        
        for name, config in server_configs.items():
            if name not in self.sessions:
                # Create new session if it doesn't exist
                cmd = config.get('command')
                args = config.get('args', [])
                env = config.get('env')
                
                if cmd:
                    session = MCPClientSession(name, cmd, args, env)
                    self.sessions[name] = session
            
            session = self.sessions[name]
            connected = await session.connect()
            
            if connected:
                tools = await session.list_tools()
                all_tools.extend(tools)
                
        return all_tools

    async def shutdown(self):
        """Shutdown all MCP sessions and ensure child processes are terminated."""
        # 1. Graceful disconnect via SDK
        for session in self.sessions.values():
            try:
                await session.disconnect()
            except:
                pass
        self.sessions = {}
        
        # 2. Force kill any remaining child processes (Final Fail-safe)
        try:
            import psutil
            current_process = psutil.Process()
            children = current_process.children(recursive=True)
            for child in children:
                try:
                    # Give it a chance to terminate normally
                    child.terminate()
                except:
                    pass
            
            # Wait a tiny bit then kill if still alive
            if children:
                _, alive = psutil.wait_procs(children, timeout=0.1)
                for p in alive:
                    try:
                        p.kill()
                    except:
                        pass
        except Exception:
            pass
