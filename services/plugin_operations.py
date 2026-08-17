"""Plugin install / uninstall / reload operations for Bark.

Extracted from ``ModuleManager`` (T4 of the clean-architecture refactor) to
restore SRP: the manager orchestrates module *discovery* and *lifecycle
registration*, while this collaborator owns the *plugin-file* lifecycle —
staging, validation, atomic replacement, registry roll-back, and the
per-guild row cleanup that makes an uninstall permanent across restarts.

``ModuleManager`` keeps thin async delegations so the public surface used by
``dashboard/routes/api/plugins.py`` and ``manifest`` stays byte-stable.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from services.plugin_manager import (
    MAX_PLUGIN_BYTES,
    PluginValidationError,
    load_plugin_class,
    validate_plugin_name,
)

if TYPE_CHECKING:
    from bot.client import BarkBot
    from modules.base import BarkContext, BarkModule
    from services.guild_module_state import GuildModuleState
    from services.module_manager import ModuleManager
    from services.module_registry import ModuleRegistry

logger = logging.getLogger("bark.services.plugin_operations")


class PluginOperations:
    """Owns the single-file plugin file lifecycle for one ``ModuleManager``."""

    def __init__(
        self,
        manager: ModuleManager,
        context: BarkContext,
        registry: ModuleRegistry,
        guild_state: GuildModuleState,
        plugin_files: dict[str, Path],
        enable_module: Callable[[str], object],
        disable_module: Callable[[str], object],
        register_module: Callable[[BarkModule], None],
        register_module_api_routes: Callable[[str], None],
        registered_api_modules: set[str],
    ) -> None:
        # ``plugin_files`` is shared by reference with ModuleDiscovery so a
        # freshly installed plugin is immediately discoverable on restart.
        # The manager is the runtime source of truth for ``bot`` (the test
        # suite swaps ``manager.bot`` to a stand-in, so we read it through the
        # manager rather than capturing a stale reference at construction).
        self._manager = manager
        self._context = context
        self._registry = registry
        self._guild_state = guild_state
        self._plugin_files = plugin_files
        self._enable_module = enable_module
        self._disable_module = disable_module
        self._register_module = register_module
        self._register_module_api_routes = register_module_api_routes
        # Shared by reference with ModuleManager so a plugin's API routes are
        # tracked/untracked on the same set.
        self._registered_api_modules = registered_api_modules

    # ── Install / uninstall / reload ──────────────────

    async def install(self, source: bytes, filename: str) -> dict:
        """Install a single-file plugin from uploaded bytes.

        Validates against a staging file, then atomically moves it into the
        plugins directory, registers the module, and enables it. Raises
        ``PluginValidationError`` on any validation failure.
        """
        from services.plugin_manager import plugins_directory

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

        if self._registry.has(name) and name not in self._plugin_files:
            staging.unlink(missing_ok=True)
            raise PluginValidationError(
                f"'{name}' is a built-in module and cannot be replaced by a plugin."
            )

        # Replacing an existing plugin: unload the old instance first.
        if name in self._plugin_files:
            await self.uninstall(name)

        destination = directory / f"{name}.py"
        staging.replace(destination)

        try:
            instance = module_class(self._context)
            self._register_module(instance)
            self._plugin_files[name] = destination
            self._register_module_api_routes(name)
            if not await self._enable_module(name):
                raise PluginValidationError(
                    "Plugin failed to enable; check its enable() method."
                )
        except Exception:
            # Roll back the registries so the failed plugin is fully inert.
            self._registry.drop(name)
            self._plugin_files.pop(name, None)
            self._registered_api_modules.discard(name)
            destination.unlink(missing_ok=True)
            raise

        # Refresh discovered permissions so plugin actions are enforced now.
        from services.response import get_permission_service

        get_permission_service().discover_module_permissions(self._registry.all())

        # Surface slash commands in Discord immediately; failure is non-fatal
        # (they reappear on the next startup sync).
        await self._maybe_sync_tree()

        logger.info("Plugin '%s' installed (v%s)", name, instance.version)
        return self.metadata(name)

    async def uninstall(self, name: str) -> bool:
        """Disable, deregister, clean up, and delete a plugin. Safe to call on
        any registered plugin; returns False when ``name`` is not a plugin.
        """
        if name not in self._plugin_files:
            return False
        path = self._plugin_files[name]

        # 1. Disable: unsubscribes events and removes commands from the tree.
        try:
            await self._disable_module(name)
        except Exception:
            logger.exception("Plugin '%s' disable() raised during uninstall", name)

        # 2. Deregister from every in-memory registry.
        self._registry.drop(name)
        self._registered_api_modules.discard(name)
        self._plugin_files.pop(name, None)
        self._guild_state.remove_module(name)

        # 3. Drop permission + role caches so no stale checks reference it.
        from services.response import clear_module_role_cache, get_permission_service

        clear_module_role_cache(name)
        get_permission_service().discover_module_permissions(self._registry.all())

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

        # Re-sync the command tree so the removed plugin's /bark commands stop
        # appearing in Discord (install syncs; uninstall must mirror it, or
        # ghost commands linger in the global tree until a restart).
        await self._maybe_sync_tree()

        logger.info("Plugin '%s' uninstalled", name)
        return True

    async def reload(self, name: str) -> bool:
        """Reload one plugin's code from its file without touching other state."""
        path = self._plugin_files.get(name)
        if path is None:
            return False
        module = self._registry.get(name)
        was_enabled = bool(module and module.enabled)
        if was_enabled and not await self._disable_module(name):
            return False
        try:
            module_class = load_plugin_class(path)
            instance = module_class(self._context)
            self._register_module(instance)
            from services.response import get_permission_service

            get_permission_service().discover_module_permissions(self._registry.all())
        except Exception:
            logger.exception("Failed to reload plugin code for '%s'", name)
            return False
        return not was_enabled or await self._enable_module(name)

    # ── Metadata helpers ───────────────────────────────

    def names(self) -> set[str]:
        return set(self._plugin_files)

    def is_plugin(self, name: str) -> bool:
        return name in self._plugin_files

    def metadata(self, name: str) -> dict:
        module = self._registry.get(name)
        return {
            "name": name,
            "version": module.version if module else "",
            "description": module.description if module else "",
            "author": module.author if module else "",
            # Instance-level availability only: whether the plugin is loaded
            # on this instance. Enablement is decided per Discord server via
            # the modules page toggle, never here.
            "loaded": bool(module is not None),
            "file": self._plugin_files[name].name if name in self._plugin_files else None,
        }

    def list_metadata(self) -> list[dict]:
        return [self.metadata(name) for name in sorted(self._plugin_files)]

    # ── Internals ──────────────────────────────────────

    @property
    def _bot(self) -> BarkBot:
        return self._manager.bot

    async def _maybe_sync_tree(self) -> None:
        """Best-effort Discord command-tree sync after an install/uninstall.

        Failure is non-fatal: commands reappear on the next startup sync. The
        original manager awaited this directly; we preserve the direct await so
        the uninstall/install tree-sync contract (and its tests) hold.
        """
        tree = getattr(self._bot, "tree", None)
        ready = getattr(self._bot, "is_ready", lambda: False)()
        if tree is not None and ready:
            try:
                await tree.sync()
            except Exception:
                logger.exception("Plugin command tree sync failed")
