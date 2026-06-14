import shlex
from typing import Any, Dict, List, Optional

from .mcp_client import MCPClientManager, MCPClientSession


def _normalize_args(args: Any) -> List[str]:
    if not isinstance(args, list):
        return []
    
    return [str(arg) for arg in args]


def _normalize_command(command: Any) -> str:
    if not isinstance(command, str):
        return ""
    return command.strip()


def _normalize_enabled(enabled: Any) -> bool:
    if isinstance(enabled, bool):
        return enabled
    if enabled is None:
        return True
    return bool(enabled)


def _normalize_name(name: Any) -> str:
    return str(name).strip()


def _is_valid_server_config(config: Dict[str, Any]) -> bool:
    return bool(config.get("name") and config.get("command"))


def _tokenize_args_text(args_text: str) -> List[str]:
    try:
        return shlex.split(args_text, posix=False)
    except ValueError:
        return []


def normalize_mcp_server_config(name: str, config: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(config, dict):
        return None

    normalized = {
        "name": _normalize_name(name),
        "command": _normalize_command(config.get("command", "")),
        "args": _normalize_args(config.get("args", [])),
        "env": _normalize_env(config.get("env", {})),
        "enabled": _normalize_enabled(config.get("enabled", True)),
    }

    if not _is_valid_server_config(normalized):
        return None

    return normalized


def normalize_mcp_servers(servers: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(servers, dict):
        return {}

    normalized = {}
    for name, config in servers.items():
        server_name = _normalize_name(name)
        if not server_name:
            continue

        normalized_config = normalize_mcp_server_config(server_name, config)
        if normalized_config is None:
            continue

        normalized[server_name] = normalized_config

    return normalized


def parse_mcp_args_input(args_text: str) -> List[str]:
    raw = (args_text or "").strip()
    if not raw:
        return []

    if raw.startswith("["):
        try:
            parsed = __import__("json").loads(raw)
        except __import__("json").JSONDecodeError as e:
            raise ValueError(f"Arguments JSON is invalid: {e}") from e
        if not isinstance(parsed, list):
            raise ValueError("Arguments JSON must be a list.")
        return [str(arg) for arg in parsed]

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) > 1:
        return lines

    return _tokenize_args_text(lines[0]) if lines else []


def _normalize_env(env: Any) -> Dict[str, str]:
    if not isinstance(env, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in env.items()
        if str(key).strip()
    }

class MCPToolProvider:
    """Loads MCP tools from normalized server configs."""

    def __init__(self, config=None, manager=None):
        self.config = config
        self.manager = manager or MCPClientManager()

    async def get_tools(self, server_configs=None):
        raw_configs = server_configs
        if raw_configs is None and self.config is not None:
            raw_configs = self.config.get_mcp_servers()

        normalized = normalize_mcp_servers(raw_configs)
        active_servers = {
            name: config
            for name, config in normalized.items()
            if config.get("enabled", True) and config.get("command")
        }

        if not active_servers:
            return []

        return await self.manager.get_all_tools(active_servers)

    async def shutdown(self):
        await self.manager.shutdown()


async def test_mcp_server_connection(name: str, server_config: Dict[str, Any]) -> List[str]:
    normalized = normalize_mcp_server_config(name, server_config)
    if normalized is None:
        raise ValueError(f"Invalid MCP server config for '{name}'.")

    session = MCPClientSession(
        normalized["name"],
        normalized["command"],
        normalized.get("args", []),
        normalized.get("env", {}),
    )

    try:
        connected = await session.connect()
        if not connected:
            raise RuntimeError(f"Failed to connect to local server '{name}'.")

        tools = await session.list_tools()
        return [tool.name for tool in tools]
    finally:
        try:
            await session.disconnect()
        except Exception:
            pass
