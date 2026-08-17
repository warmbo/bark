"""Per-guild module enablement policy.

Extracted from ``ModuleManager`` (single-responsibility split): this object owns
the ``(guild_id, module_name) -> enabled`` map and the "should run globally"
check. ``ModuleManager`` keeps the discovery, registration, lifecycle, and
dispatch concerns and delegates guild policy to this collaborator.

Rules:
- Core modules default ENABLED per guild.
- Add-on (plugin) modules default DISABLED — installing a plugin only makes it
  *available*; each server opts in explicitly via the Modules page toggle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from bot.client import BarkBot


class GuildModuleState:
    """Tracks and answers per-guild module enablement questions.

    Depends on two injected callables so it stays decoupled from
    ``ModuleManager`` internals: ``plugin_names()`` (the set of installed
    single-file plugin names) and ``has_module(name)`` (registry membership).
    """

    def __init__(
        self,
        bot: BarkBot,
        plugin_names: Callable[[], set[str]],
        has_module: Callable[[str], bool],
    ) -> None:
        self._bot = bot
        self._plugin_names = plugin_names
        self._has_module = has_module
        # (guild_id, module_name) -> enabled. Populated from persisted rows.
        self._guild_states: dict[tuple[int, str], bool] = {}

    def load(self, states) -> None:
        """Replace the cached per-guild policy from persisted rows."""
        self._guild_states = {
            (int(guild_id), str(module_name)): bool(enabled)
            for guild_id, module_name, enabled in states
        }

    def is_enabled_for_guild(self, guild_id: int, module_name: str) -> bool:
        """Return the persisted guild policy, falling back to the default.

        Core modules default enabled; add-on (plugin) modules default disabled.
        """
        if (int(guild_id), module_name) in self._guild_states:
            return self._guild_states[(int(guild_id), module_name)]
        return module_name not in self._plugin_names()

    def should_run_globally(self, module_name: str) -> bool:
        """True while at least one connected guild keeps the module enabled.

        Keeps shared module resources alive only as long as they are used.
        """
        return any(
            self.is_enabled_for_guild(guild.id, module_name)
            for guild in getattr(self._bot, "guilds", [])
        )

    def set_guild_enabled(self, guild_id: int, module_name: str, enabled: bool) -> bool:
        """Flip the per-guild execution gate. False when the module is unknown."""
        if not self._has_module(module_name):
            return False
        self._guild_states[(int(guild_id), module_name)] = bool(enabled)
        return True

    def remove_module(self, name: str) -> None:
        """Drop every guild row for a module (used on plugin uninstall)."""
        self._guild_states = {
            key: value for key, value in self._guild_states.items() if key[1] != name
        }
