"""Module package + plugin discovery.

Extracted from ``ModuleManager`` (single-responsibility split): this object
scans the ``modules`` package and the plugins directory, instantiates
``BarkModule`` instances, and registers them into a ``ModuleRegistry``. It is
created with the shared ``BarkContext`` and the plugin-files map so runtime
install/uninstall elsewhere stays in sync with what was discovered.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from pathlib import Path

from modules.base import BarkModule

logger = logging.getLogger("bark.services.module_discovery")


class ModuleDiscovery:
    """Discovers and instantiates Bark modules and single-file plugins."""

    def __init__(self, context, registry, plugin_files: dict[str, Path]) -> None:
        self._context = context
        self._registry = registry
        # Shared reference to ModuleManager's plugin-name->path map so both the
        # discovery path and the runtime install/uninstall path agree.
        self._plugin_files = plugin_files

    def discover(self) -> None:
        """Scan the modules package for BarkModule subclasses."""
        import modules

        if self._registry.names():
            logger.debug("Module discovery already completed; keeping live instances")
            return

        for _, module_name, is_pkg in pkgutil.iter_modules(modules.__path__):
            if is_pkg and module_name != "base":
                self._load_module_package(module_name)

        self.discover_plugins()

        from services.response import get_permission_service

        get_permission_service().discover_module_permissions(self._registry.all())

        logger.info(
            "Discovered %d modules: %s",
            len(self._registry.names()),
            ", ".join(self._registry.names()),
        )

    def _load_module_package(self, package_name: str) -> None:
        """Import a module package and instantiate the BarkModule subclass."""
        try:
            instance = self._instantiate_module_package(package_name)
            if instance is None:
                logger.warning("No BarkModule subclass found in modules.%s", package_name)
                return
            self._registry.register(instance)
            logger.debug("Loaded module: %s v%s", instance.name, instance.version)
        except Exception:
            logger.exception("Failed to load module package '%s'", package_name)

    def _instantiate_module_package(self, package_name: str) -> BarkModule | None:
        """Find and instantiate one module package without mutating the registry."""
        pkg = importlib.import_module(f"modules.{package_name}")
        candidates = [pkg]
        pkg_path = getattr(pkg, "__path__", None)
        if pkg_path:
            for _, sub_name, _ in pkgutil.iter_modules(pkg_path):
                try:
                    candidates.append(importlib.import_module(f"modules.{package_name}.{sub_name}"))
                except Exception:
                    logger.exception(
                        "Failed to inspect submodule modules.%s.%s",
                        package_name,
                        sub_name,
                    )

        for candidate in candidates:
            for _, obj in inspect.getmembers(candidate):
                if (
                    inspect.isclass(obj)
                    and issubclass(obj, BarkModule)
                    and obj is not BarkModule
                    and obj.__module__.startswith(f"modules.{package_name}")
                ):
                    return obj(self._context)
        return None

    def reload_package(self, package_name: str) -> BarkModule | None:
        """Reload one package's Python modules and return a fresh instance."""
        import sys

        prefix = f"modules.{package_name}"
        loaded_names = [
            name for name in sys.modules if name == prefix or name.startswith(f"{prefix}.")
        ]
        for loaded_name in sorted(loaded_names, key=lambda value: value.count("."), reverse=True):
            importlib.reload(sys.modules[loaded_name])
        return self._instantiate_module_package(package_name)

    def discover_plugins(self) -> None:
        """Load single-file plugins from the plugins directory at startup."""
        from services.plugin_manager import (
            discover_plugin_files,
            load_plugin_class,
            validate_plugin_name,
        )

        for path in discover_plugin_files():
            try:
                module_class = load_plugin_class(path)
                name = validate_plugin_name(module_class.name)
            except Exception as exc:
                logger.warning("Skipping plugin file '%s': %s", path.name, exc)
                continue
            if self._registry.has(name) or name in self._plugin_files:
                logger.warning("Skipping plugin '%s': module name already taken", name)
                continue
            try:
                instance = module_class(self._context)
                self._registry.register(instance)
                self._plugin_files[name] = path
                logger.info("Loaded plugin: %s v%s", name, instance.version)
            except Exception:
                logger.exception("Failed to instantiate plugin '%s'", name)
