"""Compatibility core for the packaged ``pylog_api`` interface."""

from __future__ import annotations

import importlib
from functools import lru_cache
from types import ModuleType
from typing import List


@lru_cache(maxsize=1)
def load_legacy_module() -> ModuleType:
    """Load the packaged legacy implementation module."""
    return importlib.import_module("pylog_api.legacy_impl")


def get_public_api_names() -> List[str]:
    """Return stable public names defined by the legacy API module."""
    legacy = load_legacy_module()
    names: List[str] = []
    for name, value in legacy.__dict__.items():
        if name.startswith("_"):
            continue
        owner = getattr(value, "__module__", None)
        if owner == legacy.__name__ or name.isupper():
            names.append(name)
    return sorted(set(names))


def get_legacy_public_callable(name: str):
    """Return the original callable from the packaged legacy implementation."""
    legacy = load_legacy_module()
    original_name = f"_original_{name}"
    if hasattr(legacy, original_name):
        return getattr(legacy, original_name)
    return getattr(legacy, name)


def __getattr__(name: str):
    """Delegate attribute access to the legacy implementation module."""
    legacy = load_legacy_module()
    try:
        return getattr(legacy, name)
    except AttributeError as exc:
        raise AttributeError(f"module 'pylog_api.core' has no attribute '{name}'") from exc


def __dir__():
    return sorted(set(globals()) | set(get_public_api_names()))
