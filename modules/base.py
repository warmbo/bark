"""
Base module class for all Bark modules.

Developer reference: docs/module-workspace.md#required-layout

Every module must subclass BarkModule and register its capabilities.
Modules interact with the system ONLY through BarkContext.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import APIRouter

    from services.bark_context import BarkContext


logger = logging.getLogger("bark.modules")


@dataclass
class CommandRegistration:
    """Describes a Discord command the module provides."""

    name: str
    description: str = ""
    slash: bool = True


@dataclass
class EventRegistration:
    """Describes an event the module listens to via EventBus."""

    event_name: str
    handler: str = ""


@dataclass
class PageRegistration:
    """Describes a dashboard page the module contributes."""

    route: str
    label: str
    icon: str = ""
    parent: str = ""
    category: str = (
        ""  # e.g. "moderation", "community", "automation", "intelligence", "governance", "settings"
    )


@dataclass
class PermissionDefinition:
    """Describes a granular permission this module defines."""

    name: str
    label: str
    description: str = ""


class BarkModule(abc.ABC):
    """Abstract base for all Bark modules."""

    name: str = "base"
    version: str = "0.1.0"
    description: str = ""
    author: str = "ZENHAWX"

    def __init__(self, ctx: BarkContext) -> None:
        self.ctx = ctx
        self.enabled: bool = False
        self._logger = logging.getLogger(f"bark.modules.{self.name}")
        # (guild_id, section) pairs whose config load failed — warn once per
        # pair so a DB outage doesn't spam logs while defaults are applied.
        self._setting_warned: set[tuple[int, str]] = set()

    @property
    def coop(self) -> "Any":
        """Shared cross-module cooperation registry (see BarkContext.coop)."""
        return self.ctx.coop

    # ── Lifecycle ─────────────────────────────────────

    @abc.abstractmethod
    async def enable(self) -> None:
        """Called when the module is enabled. Register via ctx."""
        ...

    @abc.abstractmethod
    async def disable(self) -> None:
        """Called when the module is disabled. Clean up via ctx."""
        ...

    async def reload(self) -> None:
        """Disable then re-enable."""
        self._logger.info("Reloading module '%s'", self.name)
        await self.disable()
        await self.enable()
        self._logger.info("Module '%s' reloaded", self.name)

    # ── Registration declarations (read by ModuleManager) ──

    def get_settings_schema(self) -> dict[str, Any]:
        """
        JSON Schema for this module's configuration.
        Used by the dashboard to render config forms.
        """
        return {}

    # Whether the dashboard renders the Configure tab. Modules that manage
    # configuration purely through other means (e.g. a dedicated tab or the
    # slash command surface) can hide the generic settings form.
    show_configure_tab: bool = True

    # Configure-panel layout: None (stacked single column) or "columns" —
    # modules with many grouped subsections disperse them into a balanced
    # multi-column grid for readability.
    config_layout: str | None = None

    def normalize_config(self, raw: dict[str, Any]) -> dict[str, Any]:
        """
        Normalize a stored config into the shape declared by
        ``get_settings_schema`` before validation or display.

        Modules that historically stored flat keys and now declare a grouped
        schema override this to lift legacy keys into the current shape
        (e.g. auto_voice). The default is the identity — most modules store
        exactly the shape they declare.
        """
        return raw

    async def load_dashboard_config(self, guild_id: int) -> dict[str, Any]:
        """Load the authoritative configuration shown by the dashboard."""
        return await self.ctx.get_module_config(self.name, guild_id)

    async def save_dashboard_config(self, guild_id: int, config: dict[str, Any]) -> None:
        """Persist the authoritative dashboard configuration."""
        await self.ctx.save_module_config(self.name, guild_id, config)

    def get_dashboard_pages(self) -> list[PageRegistration]:
        return []

    def get_commands(self) -> list[CommandRegistration]:
        return []

    def get_events(self) -> list[EventRegistration]:
        return []

    def get_permissions(self) -> list[PermissionDefinition]:
        return []

    def get_api_routes(self) -> APIRouter | None:
        return None

    def get_extra_tabs(self) -> list[dict]:
        """Return extra dashboard tabs for this module.
        Each tab: {"id": str, "label": str, "html": str (Jinja2 template content)}"""
        return []

    # ── About Stories ──────────────────────────────────

    def get_about(self) -> list[dict]:
        """
        Return a list of about-story dicts for the dashboard About section.
        Each dict: {title, description} or {title, stories: [{prefix, text}]}
        Override in each module.
        """
        return []

    # ── Module Actions (dashboard-doable operations) ───

    def get_actions(self) -> list[dict]:
        """
        Return a list of action forms for the dashboard.
        Each action is a dict with:
          - id: unique action name
          - label: button/header text
          - description: help text shown above the form
          - fields: list of {"key", "label", "type", "required", "placeholder"}
          - endpoint: API endpoint path (relative to /api/v1/guilds/{id}/modules/{name}/)
        """
        return []

    # ── Dashboard Widgets (add-on dashboard sections) ──

    async def get_dashboard_cards(self, guild_id: int) -> list[dict]:
        """
        Return dashboard widget cards this module contributes to the server
        overview (dashboard) page.

        A card is a serializable dict:
          - id: unique card id (module-prefixed, e.g. ``reputation_top``)
          - title: card heading
          - icon: lucide icon name (optional)
          - description: short helper text (optional)
          - type: ``"list"`` (default) — items render as rows with a label/value
            and optional icon; ``"metric"`` — a headline number with an optional
            ``sparkline`` series.
          - items: for ``"list"``, list of {"label", "value", "subtitle"?, "icon"?}
          - value: for ``"metric"``, the headline number/string.
          - sparkline: for ``"metric"``, a list of numbers rendered as a tiny
            inline trend.
          - link: optional route (e.g. ``/guild/{id}/modules/{name}``) rendered
            as a "View in module" footer link.

        Modules return empty by default. This is the extension point for
        add-on dashboard sections (e.g. a birthdays module's "Upcoming
        Birthdays"). Only cards from modules enabled for the guild are shown.
        Cross-module composition is available through ``self.coop`` providers.
        """
        return []

    # ── Module Stats (backup/export support) ──────────

    async def export_stats(self, guild_id: int) -> dict[str, Any]:
        """Return this module's stats for the guild as JSON-safe data.

        Included in the dashboard Export backup. Default: no stats.
        """
        return {}

    async def import_stats(self, guild_id: int, stats: dict[str, Any]) -> list[str]:
        """Apply stats restored from an exported backup for the guild.

        Return a list of human-readable summary lines for the import report.
        """
        return []

    # ── Helpers ───────────────────────────────────────

    def command_group_name(self) -> str:
        """The instance's slash-command group name (e.g. ``'bark'``, ``'bob'``).

        Derived from the ``BARK_COMMAND_GROUP`` override, else the bot's
        username (see ``ModuleManager.command_group_name``). Available to every
        module — including add-on plugins — so module pages, help text and
        command lists can render the correct slash-command prefix instead of a
        hardcoded ``/bark``.
        """
        manager = getattr(getattr(self.ctx, "bot", None), "modules", None)
        if manager is not None and hasattr(manager, "command_group_name"):
            return manager.command_group_name()
        from config import config, sanitize_command_group

        return sanitize_command_group(config.bot.command_group or "bark")

    async def _get_setting(self, guild_id: int, section: str, key: str, default=None):
        """Read a value from this module's stored config, with dot-path traversal.

        A config-load FAILURE must not silently flip moderation defaults (e.g.
        auto-kick based on a broken read) — surface it once per (guild, section).
        Defaults are only legitimate when the key is genuinely absent.
        """
        try:
            settings = await self.ctx.get_module_config(self.name, guild_id)
        except Exception:
            if (guild_id, section) not in self._setting_warned:
                self._setting_warned.add((guild_id, section))
                self._logger.warning(
                    "Failed to load config for guild %s section '%s' — using defaults",
                    guild_id,
                    section,
                )
            return default
        section_data = settings.get(section, {})
        if not isinstance(section_data, dict):
            return default
        return section_data.get(key, default)

    def log(self, level: str, msg: str, **kwargs) -> None:
        getattr(self._logger, level, self._logger.info)(msg, **kwargs)

    def __repr__(self) -> str:
        return f"<BarkModule name='{self.name}' v{self.version} enabled={self.enabled}>"
