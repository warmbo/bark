"""
Module discovery and lifecycle management.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from typing import TYPE_CHECKING, Any

from modules.base import BarkModule, PageRegistration

if TYPE_CHECKING:
    from bot.client import BarkBot

logger = logging.getLogger("bark.services.module_manager")


class ModuleManager:
    """
    Discovers, loads, enables, and manages Bark modules.

    Modules are auto-discovered from the modules/ package at startup.
    Each guild has its own set of enabled/disabled modules and config.
    """

    def __init__(self, bot: BarkBot) -> None:
        self.bot = bot
        self._modules: dict[str, BarkModule] = {}
        self._page_registry: dict[str, list[PageRegistration]] = {}

    # ── Discovery ─────────────────────────────────────

    def discover(self) -> None:
        """Scan the modules package for BarkModule subclasses."""
        import modules

        self._modules = {}
        self._page_registry = {}

        for _, module_name, is_pkg in pkgutil.iter_modules(modules.__path__):
            if is_pkg and module_name != "base":
                self._load_module_package(module_name)

        logger.info(
            "Discovered %d modules: %s",
            len(self._modules),
            ", ".join(self._modules.keys()),
        )

    def _load_module_package(self, package_name: str) -> None:
        """Import a module package and find the BarkModule subclass."""
        try:
            pkg = importlib.import_module(f"modules.{package_name}")

            # Search the package itself and all its submodules for BarkModule subclasses
            for name, obj in inspect.getmembers(pkg):
                if (
                    inspect.isclass(obj)
                    and issubclass(obj, BarkModule)
                    and obj is not BarkModule
                ):
                    instance = obj(self.bot)
                    self._modules[instance.name] = instance
                    self._page_registry[instance.name] = instance.get_dashboard_pages()
                    logger.debug("Loaded module: %s v%s", instance.name, instance.version)
                    return

            # Also scan submodules within the package
            try:
                pkg_path = pkg.__path__
            except AttributeError:
                pkg_path = None

            if pkg_path:
                for _, sub_name, _ in pkgutil.iter_modules(pkg_path):
                    try:
                        sub = importlib.import_module(f"modules.{package_name}.{sub_name}")
                        for _, obj in inspect.getmembers(sub):
                            if (
                                inspect.isclass(obj)
                                and issubclass(obj, BarkModule)
                                and obj is not BarkModule
                            ):
                                instance = obj(self.bot)
                                self._modules[instance.name] = instance
                                self._page_registry[instance.name] = instance.get_dashboard_pages()
                                logger.debug("Loaded module: %s v%s from %s", instance.name, instance.version, sub_name)
                                return
                    except Exception:
                        logger.debug("Could not scan submodule %s.%s", package_name, sub_name)

            logger.warning("No BarkModule subclass found in modules.%s", package_name)
        except Exception:
            logger.exception("Failed to load module package '%s'", package_name)

    # ── Lifecycle ─────────────────────────────────────

    async def enable_module(self, name: str) -> bool:
        """Enable a module by name."""
        module = self._modules.get(name)
        if module is None:
            logger.warning("Cannot enable unknown module '%s'", name)
            return False
        if module.enabled:
            logger.debug("Module '%s' already enabled", name)
            return True
        try:
            await module.enable()
            module.enabled = True
            logger.info("Module '%s' enabled", name)
            return True
        except Exception:
            logger.exception("Failed to enable module '%s'", name)
            return False

    async def disable_module(self, name: str) -> bool:
        """Disable a module by name."""
        module = self._modules.get(name)
        if module is None:
            return False
        if not module.enabled:
            return True
        try:
            await module.disable()
            module.enabled = False
            logger.info("Module '%s' disabled", name)
            return True
        except Exception:
            logger.exception("Failed to disable module '%s'", name)
            return False

    async def reload_module(self, name: str) -> bool:
        """Reload a module."""
        module = self._modules.get(name)
        if module is None:
            return False
        try:
            await module.reload()
            return True
        except Exception:
            logger.exception("Failed to reload module '%s'", name)
            return False

    async def enable_all(self, guild_modules: list[dict]) -> None:
        """Enable all modules that should be active for a guild."""
        for gm in guild_modules:
            if gm.get("enabled"):
                await self.enable_module(gm["module_name"])

    async def disable_all(self) -> None:
        """Disable all modules."""
        for name in list(self._modules.keys()):
            await self.disable_module(name)

    # ── Queries ───────────────────────────────────────

    def get_module(self, name: str) -> BarkModule | None:
        return self._modules.get(name)

    def get_all_modules(self) -> dict[str, BarkModule]:
        return dict(self._modules)

    def get_enabled_modules(self) -> dict[str, BarkModule]:
        return {n: m for n, m in self._modules.items() if m.enabled}

    def get_dashboard_pages(self) -> dict[str, list[PageRegistration]]:
        return dict(self._page_registry)

    def get_all_commands(self) -> list:
        """Aggregate command registrations from all modules."""
        commands = []
        for module in self._modules.values():
            commands.extend(module.get_commands())
        return commands

    def get_all_events(self) -> list:
        """Aggregate event registrations from all modules."""
        events = []
        for module in self._modules.values():
            events.extend(module.get_events())
        return events
