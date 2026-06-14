"""API reflection helpers for the packaged ``pylog_api`` interface."""

from __future__ import annotations

from typing import Any, Dict

from .api_metadata import API_METADATA


def inspect_api(name: str) -> Dict[str, Any]:
    """Return machine-readable signature and documentation for a specific API."""
    return API_METADATA.get(name, {"error": f"API function '{name}' not found in registry."})
