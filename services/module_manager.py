"""
Module discovery and lifecycle management.

Lifecycle reference: README.md#module-lifecycle

Centralizes command registration, event subscription, and
module lifecycle across the entire system.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from functools import wraps
from typing import TYPE_CHECKING, Callable

from modules.base import BarkModule, PageRegistration
from services.bark_context import BarkContext
from services.event_bus import EventBus

if TYPE_CHECKING:
    from bot.client import BarkBot

logger = logging.getLogger("bark.services.module_manager")


class ModuleManager:
    """
    Discovers, loads, enables, and manages all Bark modules.

    All command registration and event subscription flows through
    this manager. Modules declare their capabilities; the manager
    handles registration with the bot runtime and EventBus.
    """

    def __init__(self, bot: BarkBot) -> None:
        self.bot = bot
        self._event_bus = EventBus()
        self._context = BarkContext(self.bot, self._event_bus)
        self._modules: dict[str, BarkModule] = {}
        self._page_registry: dict[str, list[PageRegistration]] = {}
        self._registered_commands: dict[str, set[str]] = {}  # module -> {command names}
        self._registered_events: dict[
            str, list[tuple[str, Callable]]
        ] = {}  # module -> [(event_type, handler)]
        self._registered_api_modules: set[str] = set()
        self._guild_states: dict[tuple[int, str], bool] = {}

    # ── Discovery ─────────────────────────────────────

    def discover(self) -> None:
        """Scan the modules package for BarkModule subclasses."""
        import modules

        if self._modules:
            logger.debug("Module discovery already completed; keeping live instances")
            return

        for _, module_name, is_pkg in pkgutil.iter_modules(modules.__path__):
            if is_pkg and module_name != "base":
                self._load_module_package(module_name)

        from services.response import get_permission_service

        get_permission_service().discover_module_permissions(self._modules)

        logger.info(
            "Discovered %d modules: %s",
            len(self._modules),
            ", ".join(self._modules.keys()),
        )

    def _load_module_package(self, package_name: str) -> None:
        """Import a module package and instantiate the BarkModule subclass."""
        try:
            instance = self._instantiate_module_package(package_name)
            if instance is None:
                logger.warning("No BarkModule subclass found in modules.%s", package_name)
                return
            self._register_module(instance)
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

    def _reload_module_package(self, package_name: str) -> BarkModule | None:
        """Reload one package's Python modules and return a fresh instance."""
        import sys

        prefix = f"modules.{package_name}"
        loaded_names = [
            name for name in sys.modules if name == prefix or name.startswith(f"{prefix}.")
        ]
        for loaded_name in sorted(loaded_names, key=lambda value: value.count("."), reverse=True):
            importlib.reload(sys.modules[loaded_name])
        return self._instantiate_module_package(package_name)

    def _register_module(self, module: BarkModule) -> None:
        """Store module and its page registrations."""
        self._modules[module.name] = module
        self._page_registry[module.name] = module.get_dashboard_pages()
        logger.debug("Loaded module: %s v%s", module.name, module.version)

    # ── Lifecycle ─────────────────────────────────────

    async def enable_module(self, name: str) -> bool:
        """Enable a module: registers its commands and subscribes its events."""
        module = self._modules.get(name)
        if module is None:
            return False
        if module.enabled:
            return True

        try:
            await module.enable()

            # Centralized command registration
            self._registered_commands[name] = set()
            for cmd in module.get_commands():
                if cmd.slash:
                    factory = getattr(module, f"_make_{cmd.name}_command", None)
                    if factory:
                        app_cmd = factory()
                        if hasattr(app_cmd, "add_check"):
                            app_cmd.add_check(self._command_enabled_check(name))
                        if getattr(self.bot, "tree", None) is not None:
                            self.bot.tree.add_command(app_cmd)
                        self._registered_commands[name].add(cmd.name)

            # Centralized event subscription via EventBus
            self._registered_events[name] = []
            for evt in module.get_events():
                handler_name = evt.handler or f"_on_{evt.event_name.removeprefix('on_')}"
                handler = getattr(module, handler_name, None)
                if handler is None:
                    raise AttributeError(
                        f"Module '{name}' declares event '{evt.event_name}' "
                        f"without handler '{handler_name}'"
                    )
                guarded_handler = self._guard_event_handler(name, handler)
                self._event_bus.subscribe(evt.event_name, guarded_handler)
                self._registered_events[name].append((evt.event_name, guarded_handler))

            module.enabled = True
            logger.info(
                "Module '%s' enabled (%d commands, %d events)",
                name,
                len(self._registered_commands[name]),
                len(self._registered_events[name]),
            )
            return True
        except Exception:
            logger.exception("Failed to enable module '%s'", name)
            for event_type, handler in self._registered_events.get(name, []):
                self._event_bus.unsubscribe(event_type, handler)
            self._registered_events.get(name, []).clear()
            for command_name in self._registered_commands.get(name, set()):
                if getattr(self.bot, "tree", None) is not None:
                    try:
                        self.bot.tree.remove_command(command_name)
                    except Exception:
                        logger.exception(
                            "Failed to roll back command '%s' for module '%s'",
                            command_name,
                            name,
                        )
            self._registered_commands.get(name, set()).clear()
            try:
                await module.disable()
            except Exception:
                logger.exception("Failed to roll back module '%s' lifecycle", name)
            module.enabled = False
            return False

    async def disable_module(self, name: str) -> bool:
        """Disable a module: unregisters commands and unsubscribes events."""
        module = self._modules.get(name)
        if module is None or not module.enabled:
            return True

        try:
            await module.disable()

            # Unregister commands
            if name in self._registered_commands:
                for cmd_name in self._registered_commands[name]:
                    if hasattr(self.bot, "tree"):
                        try:
                            self.bot.tree.remove_command(cmd_name)
                        except Exception:
                            pass
                self._registered_commands[name].clear()

            # Unsubscribe events — handler-specific so we don't nuke other modules
            if name in self._registered_events:
                for evt_type, handler in self._registered_events[name]:
                    self._event_bus.unsubscribe(evt_type, handler)
                self._registered_events[name].clear()

            module.enabled = False
            logger.info("Module '%s' disabled", name)
            return True
        except Exception:
            logger.exception("Failed to disable module '%s'", name)
            return False

    async def reload_module(self, name: str) -> bool:
        """Reload one module without disturbing any other live plugin."""
        original = self._modules.get(name)
        if original is None:
            return False
        was_enabled = original.enabled
        if was_enabled and not await self.disable_module(name):
            return False

        # FastAPI cannot remove routes after startup. Once this module's router
        # is mounted, keep the instance captured by its route handlers and do a
        # clean lifecycle restart rather than leaving stale closures behind.
        if name in self._registered_api_modules:
            return not was_enabled or await self.enable_module(name)

        try:
            replacement = self._reload_module_package(name)
            if replacement is None:
                raise RuntimeError(f"No BarkModule subclass found for '{name}'")
            self._register_module(replacement)
        except Exception:
            logger.exception("Failed to reload module code for '%s'", name)
            self._register_module(original)
            if was_enabled:
                await self.enable_module(name)
            return False

        return not was_enabled or await self.enable_module(name)
    async def disable_all(self) -> None:
        """Disable all modules."""
        for name in list(self._modules.keys()):
            await self.disable_module(name)

    def load_guild_states(self, states) -> None:
        """Replace cached per-guild module policy from persisted rows."""
        self._guild_states = {
            (int(guild_id), str(module_name)): bool(enabled)
            for guild_id, module_name, enabled in states
        }

    def is_enabled_for_guild(self, guild_id: int, module_name: str) -> bool:
        """Return persisted guild policy; modules default enabled."""
        return self._guild_states.get((int(guild_id), module_name), True)

    def should_run_globally(self, module_name: str) -> bool:
        """Keep shared resources alive while at least one connected guild uses them."""
        return any(
            self.is_enabled_for_guild(guild.id, module_name)
            for guild in getattr(self.bot, "guilds", [])
        )

    async def set_guild_enabled(self, guild_id: int, module_name: str, enabled: bool) -> bool:
        """Update guild policy and reconcile shared module lifecycle."""
        if module_name not in self._modules:
            return False
        self._guild_states[(int(guild_id), module_name)] = bool(enabled)
        if enabled:
            return await self.enable_module(module_name)
        if not self.should_run_globally(module_name):
            return await self.disable_module(module_name)
        return True

    def _guard_event_handler(self, module_name: str, handler: Callable) -> Callable:
        @wraps(handler)
        async def guarded(event_type: str, **data):
            guild_id = self._event_guild_id(data)
            if guild_id is not None and not self.is_enabled_for_guild(guild_id, module_name):
                return None
            return await handler(event_type, **data)

        return guarded

    def _command_enabled_check(self, module_name: str) -> Callable:
        async def enabled_for_interaction(interaction) -> bool:
            guild_id = getattr(interaction, "guild_id", None)
            return guild_id is None or self.is_enabled_for_guild(guild_id, module_name)

        return enabled_for_interaction

    @staticmethod
    def _event_guild_id(data: dict) -> int | None:
        guild = data.get("guild")
        if guild is not None and getattr(guild, "id", None) is not None:
            return int(guild.id)
        for value in data.values():
            value_guild = getattr(value, "guild", None)
            if value_guild is not None and getattr(value_guild, "id", None) is not None:
                return int(value_guild.id)
            value_guild_id = getattr(value, "guild_id", None)
            if value_guild_id is not None:
                return int(value_guild_id)
        return None

    # ── Queries ───────────────────────────────────────

    def get_module(self, name: str) -> BarkModule | None:
        return self._modules.get(name)

    def get_all_modules(self) -> dict[str, BarkModule]:
        return dict(self._modules)

    def get_enabled_modules(self) -> dict[str, BarkModule]:
        return {n: m for n, m in self._modules.items() if m.enabled}

    def get_dashboard_pages(self) -> dict[str, list[PageRegistration]]:
        return dict(self._page_registry)

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    # ── API route registration (called by dashboard) ───────

    def register_api_routes(self, app) -> None:
        """Register each module's API routes with the FastAPI app."""
        for name, module in self._modules.items():
            if name in self._registered_api_modules:
                continue
            router = module.get_api_routes()
            if router is not None:
                app.include_router(router, prefix="/api/v1")
                self._registered_api_modules.add(name)
                logger.debug("Registered API routes for module '%s'", name)
