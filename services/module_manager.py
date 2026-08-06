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
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from discord.app_commands import Group

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
        # Runtime-installed single-file plugins: module name -> file path.
        self._plugin_files: dict[str, Path] = {}
        # The single /bark group that hosts every module command. Created
        # lazily on first module enable so all commands share one namespace
        # (e.g. /bark trivia start instead of /trivia start).
        self._bark_group: Group | None = None
        # module -> {command name -> owning subgroup (None = direct /bark child)}
        self._command_owners: dict[str, dict[str, object]] = {}

    # ── Command namespace ─────────────────────────────

    def _get_bark_group(self):
        """Return the shared /bark group, registering it on the tree once."""
        if self._bark_group is not None:
            return self._bark_group
        from discord.app_commands import Group

        group = Group(
            name="bark",
            description="Bark commands — every module's commands live under this one.",
        )
        self._bark_group = group
        if getattr(self.bot, "tree", None) is not None:
            self.bot.tree.add_command(group, guild=self._command_guild())
        return group

    def _module_subgroup(self, module_name: str, description: str):
        """Return (creating once) the /bark subgroup for a module's commands.

        Discord limits a group to 25 children, so plain commands are grouped
        per module (/bark moderation warn) while modules that already expose a
        namespaced group (e.g. /bark trivia start) hang directly off /bark.
        """
        from discord.app_commands import Group

        bark = self._get_bark_group()
        existing = next((c for c in bark.commands if c.name == module_name), None)
        if existing is None:
            existing = Group(
                name=module_name,
                description=(description or f"{module_name} commands")[:100],
            )
            bark.add_command(existing)
        return existing

    def _unregister_command(self, module_name: str, command_name: str) -> None:
        """Remove a module command from the /bark namespace."""
        if self._bark_group is None:
            return
        try:
            parent = self._command_owners.get(module_name, {}).get(command_name)
            if parent is None:
                self._bark_group.remove_command(command_name)
            else:
                parent.remove_command(command_name)
                # Discord rejects groups without children — drop empty subgroups.
                if not getattr(parent, "commands", None):
                    self._bark_group.remove_command(parent.name)
        except Exception:
            logger.exception(
                "Failed to remove command '%s' for module '%s'",
                command_name,
                module_name,
            )

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

        self.discover_plugins()

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

    # ── Plugins (single-file modules) ─────────────────

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
            if name in self._modules or name in self._plugin_files:
                logger.warning("Skipping plugin '%s': module name already taken", name)
                continue
            try:
                instance = module_class(self._context)
                self._register_module(instance)
                self._plugin_files[name] = path
                logger.info("Loaded plugin: %s v%s", name, instance.version)
            except Exception:
                logger.exception("Failed to instantiate plugin '%s'", name)

    def is_plugin(self, name: str) -> bool:
        """Return True when ``name`` is a runtime-installed single-file plugin."""
        return name in self._plugin_files

    def plugin_names(self) -> set[str]:
        """Return the names of all installed plugins."""
        return set(self._plugin_files)

    def list_plugins(self) -> list[dict]:
        """Return metadata for every installed plugin, sorted by name."""
        return [self._plugin_metadata(name) for name in sorted(self._plugin_files)]

    def _plugin_metadata(self, name: str) -> dict:
        module = self._modules.get(name)
        return {
            "name": name,
            "version": module.version if module else "",
            "description": module.description if module else "",
            "author": module.author if module else "",
            "enabled": bool(module and module.enabled),
            "file": self._plugin_files[name].name if name in self._plugin_files else None,
        }

    async def install_plugin(self, source: bytes, filename: str) -> dict:
        """Install a single-file plugin from uploaded bytes.

        Validates the upload against a staging file, then atomically moves it
        into the plugins directory, registers the module, and enables it.
        Raises PluginValidationError on any validation failure.
        """
        import uuid

        from services.plugin_manager import (
            MAX_PLUGIN_BYTES,
            PluginValidationError,
            load_plugin_class,
            plugins_directory,
            validate_plugin_name,
        )

        if not filename.endswith(".py"):
            raise PluginValidationError("Plugin must be a single .py file.")
        if not source:
            raise PluginValidationError("Uploaded file is empty.")
        if len(source) > MAX_PLUGIN_BYTES:
            raise PluginValidationError("Plugin exceeds the 512 KB size limit.")

        directory = plugins_directory()
        staging = directory / f".staging-{uuid.uuid4().hex}.py"
        try:
            staging.write_bytes(source)
            module_class = load_plugin_class(staging)
            name = validate_plugin_name(module_class.name)
        except Exception:
            staging.unlink(missing_ok=True)
            raise

        if name in self._modules and name not in self._plugin_files:
            staging.unlink(missing_ok=True)
            raise PluginValidationError(
                f"'{name}' is a built-in module and cannot be replaced by a plugin."
            )

        # Replacing an existing plugin: unload the old instance first.
        if name in self._plugin_files:
            await self.uninstall_plugin(name)

        destination = directory / f"{name}.py"
        staging.replace(destination)

        try:
            instance = module_class(self._context)
            self._register_module(instance)
            self._plugin_files[name] = destination
            self._register_module_api_routes(name)
            if not await self.enable_module(name):
                raise PluginValidationError(
                    "Plugin failed to enable; check its enable() method."
                )
        except Exception:
            # Roll back the registries so the failed plugin is fully inert.
            self._modules.pop(name, None)
            self._page_registry.pop(name, None)
            self._plugin_files.pop(name, None)
            self._registered_api_modules.discard(name)
            destination.unlink(missing_ok=True)
            raise

        # Refresh discovered permissions so plugin actions are enforced now.
        from services.response import get_permission_service

        get_permission_service().discover_module_permissions(self._modules)

        # Surface slash commands in Discord immediately; failure is non-fatal
        # (they reappear on the next startup sync).
        if (
            getattr(self.bot, "tree", None) is not None
            and getattr(self.bot, "is_ready", lambda: False)()
        ):
            try:
                await self.bot.tree.sync()
            except Exception:
                logger.exception(
                    "Plugin '%s' installed but slash command sync failed", name
                )

        logger.info("Plugin '%s' installed (v%s)", name, instance.version)
        return self._plugin_metadata(name)

    async def uninstall_plugin(self, name: str) -> bool:
        """Disable, deregister, clean up, and delete a plugin. Safe to call on
        any registered plugin; returns False when ``name`` is not a plugin."""
        if name not in self._plugin_files:
            return False
        path = self._plugin_files[name]

        # 1. Disable: unsubscribes events and removes commands from the tree.
        try:
            await self.disable_module(name)
        except Exception:
            logger.exception("Plugin '%s' disable() raised during uninstall", name)

        # 2. Deregister from every in-memory registry.
        self._modules.pop(name, None)
        self._page_registry.pop(name, None)
        self._registered_commands.pop(name, None)
        self._registered_events.pop(name, None)
        self._registered_api_modules.discard(name)
        self._plugin_files.pop(name, None)
        self._guild_states = {
            key: value for key, value in self._guild_states.items() if key[1] != name
        }

        # 3. Drop permission + role caches so no stale checks reference it.
        from services.response import clear_module_role_cache, get_permission_service

        clear_module_role_cache(name)
        get_permission_service().discover_module_permissions(self._modules)

        # 4. Remove per-guild rows so the module cannot resurface after restart.
        from sqlalchemy import delete

        from database.engine import session_scope
        from database.models.module import ModuleConfig
        from database.models.permissions import ModuleRoleAccess

        async with session_scope() as session:
            await session.execute(
                delete(ModuleConfig).where(ModuleConfig.module_name == name)
            )
            await session.execute(
                delete(ModuleRoleAccess).where(ModuleRoleAccess.module_name == name)
            )
            await session.commit()

        # 5. Delete the file last so a crash leaves a recoverable state.
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Plugin '%s' file could not be deleted", name)

        logger.info("Plugin '%s' uninstalled", name)
        return True

    async def _reload_plugin(self, name: str) -> bool:
        """Reload one plugin's code from its file without touching other state."""
        path = self._plugin_files.get(name)
        if path is None:
            return False
        module = self._modules.get(name)
        was_enabled = bool(module and module.enabled)
        if was_enabled and not await self.disable_module(name):
            return False
        try:
            from services.plugin_manager import load_plugin_class

            module_class = load_plugin_class(path)
            instance = module_class(self._context)
            self._register_module(instance)
            from services.response import get_permission_service

            get_permission_service().discover_module_permissions(self._modules)
        except Exception:
            logger.exception("Failed to reload plugin code for '%s'", name)
            return False
        return not was_enabled or await self.enable_module(name)

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
                            from discord.app_commands import Group

                            single_command_module = (
                                len([c for c in module.get_commands() if c.slash]) == 1
                            )
                            if isinstance(app_cmd, Group) or single_command_module:
                                # /bark trivia start or /bark roll — namespaced
                                # groups and single-command modules hang directly
                                # off /bark (staying under Discord's 25-child cap).
                                self._get_bark_group().add_command(app_cmd)
                                self._command_owners.setdefault(name, {})[cmd.name] = None
                            else:
                                # Multi-command module: subgroup, e.g. /bark moderation warn
                                subgroup = self._module_subgroup(name, module.description)
                                subgroup.add_command(app_cmd)
                                self._command_owners.setdefault(name, {})[cmd.name] = subgroup
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
                        self._unregister_command(name, command_name)
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
                            self._unregister_command(name, cmd_name)
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
        if name in self._plugin_files:
            return await self._reload_plugin(name)
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

    def _command_guild(self):
        """Return the sync-guild Object when BARK_SYNC_GUILD_ID is configured.

        Commands registered with a guild scope sync instantly to that guild
        (no global-command cache), which is ideal for dev instances.
        """
        try:
            import discord

            from config import config

            if config.bot.sync_guild_id:
                return discord.Object(id=config.bot.sync_guild_id)
        except Exception:
            pass
        return None

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
        for name in list(self._modules.keys()):
            self._register_module_api_routes(name)

    def _register_module_api_routes(self, name: str) -> None:
        """Register one module's API routes with the dashboard app.

        Plugin routers are wrapped with an availability guard so their routes
        answer 404 once the plugin is removed — FastAPI cannot un-register
        routes after startup.
        """
        app = getattr(self.bot, "app", None)
        if app is None or name in self._registered_api_modules:
            return
        module = self._modules.get(name)
        if module is None:
            return
        router = module.get_api_routes()
        if router is None:
            return
        if name in self._plugin_files:
            router = self._guard_plugin_router(name, router)
        app.include_router(router, prefix="/api/v1")
        self._registered_api_modules.add(name)
        logger.debug("Registered API routes for module '%s'", name)

    def _guard_plugin_router(self, plugin_name: str, router):
        """Wrap a plugin router so every route 404s once the plugin is removed.

        Removing a plugin leaves its route objects mounted (FastAPI cannot
        un-register them), but the guard makes them inert: they check the live
        registry on every request and answer 404 when the module is gone.
        """
        from fastapi import APIRouter, Depends, HTTPException

        async def _plugin_present() -> None:
            if self.get_module(plugin_name) is None:
                raise HTTPException(status_code=404, detail="Plugin not installed")

        wrapper = APIRouter(dependencies=[Depends(_plugin_present)])
        wrapper.include_router(router)
        return wrapper
