"""
Single-file plugin management for Bark.

Plugins are distributable as a single ``.py`` file containing exactly one
``BarkModule`` subclass. Files live in ``<data_dir>/plugins/<name>.py`` and can
be installed or removed at runtime from the dashboard without restarting the
bot (see dashboard/routes/api/plugins.py).

IMPORTANT: a plugin file is user-supplied code — installing a plugin executes
it. The install/remove endpoints are therefore restricted to instance owners
(or fully permissive when OAuth is not configured).
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from modules.base import BarkModule

if TYPE_CHECKING:
    pass

logger = logging.getLogger("bark.services.plugin_manager")

MAX_PLUGIN_BYTES = 512 * 1024
PLUGIN_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")

# Modules shipped inside the app itself can never be managed as plugins.
CORE_MODULES = {
    "announcements",
    "auto_voice",
    "logging",
    "moderation",
    "reputation",
    "role_manager",
    "welcome",
}

RESERVED_NAMES = {"base", "__init__", "plugins", "modules", "bot", "config"}


class PluginValidationError(ValueError):
    """Raised when an uploaded file is not a valid single-file Bark plugin."""


def plugins_directory() -> Path:
    """Return the directory where plugin files are stored, creating it if needed."""
    from config import config

    directory = Path(config.data_dir) / "plugins"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def discover_plugin_files() -> list[Path]:
    """Return plugin files on disk, sorted by name."""
    directory = plugins_directory()
    if not directory.exists():
        return []
    return sorted(path for path in directory.glob("*.py") if path.is_file())


def is_core_module(name: str) -> bool:
    """Return True when ``name`` is a module shipped inside the app."""
    return name in CORE_MODULES


def validate_plugin_name(name: str) -> str:
    """Validate a plugin module name; return it unchanged when valid.

    Raises PluginValidationError when the name is not a safe Python identifier
    or collides with a built-in/reserved module.
    """
    if not isinstance(name, str) or not PLUGIN_NAME_RE.fullmatch(name):
        raise PluginValidationError(
            "Module name must be 2-32 lowercase characters (letters, digits, underscores)."
        )
    if name in RESERVED_NAMES or is_core_module(name):
        raise PluginValidationError(f"'{name}' is a reserved or built-in module name.")
    return name


def _plugin_module_name(name: str) -> str:
    """Synthetic top-level module name used to import a plugin file."""
    return f"_bark_plugin_{name}"


def load_plugin_class(path: Path) -> type[BarkModule]:
    """Import a plugin file and return its single BarkModule subclass.

    The file must define exactly one ``BarkModule`` subclass. Raises
    PluginValidationError when the file cannot be imported or does not match
    that contract.
    """
    module_name = _plugin_module_name(path.stem)
    # A previous import of the same plugin (reinstall/reload) must not shadow
    # the fresh file contents.
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PluginValidationError("Could not parse the plugin file.")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise PluginValidationError(f"Plugin failed to import: {exc}") from exc
    sys.modules[module_name] = module

    classes = [
        obj
        for _, obj in inspect.getmembers(module, inspect.isclass)
        if issubclass(obj, BarkModule)
        and obj is not BarkModule
        and obj.__module__ == module_name
    ]
    if not classes:
        raise PluginValidationError(
            "No BarkModule subclass found. Define one class extending "
            "modules.base.BarkModule."
        )
    if len(classes) > 1:
        raise PluginValidationError(
            "Plugin must define exactly one BarkModule subclass; "
            f"found {len(classes)} ({', '.join(cls.__name__ for cls in classes)})."
        )
    return classes[0]
