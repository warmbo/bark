"""
Base module class for all Bark modules.

Every module must subclass BarkModule and register its capabilities.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bot.client import BarkBot
    from fastapi import APIRouter


logger = logging.getLogger("bark.modules")


@dataclass
class CommandRegistration:
    """Describes a Discord command the module wants to register."""
    name: str
    description: str = ""
    slash: bool = True
    prefix: bool = True


@dataclass
class EventRegistration:
    """Describes a Discord event the module wants to listen to."""
    event_name: str  # e.g. "on_message", "on_member_join"


@dataclass
class PageRegistration:
    """Describes a dashboard page the module provides."""
    route: str       # e.g. "/guild/{guild_id}/moderation/cases"
    label: str       # e.g. "Cases"
    icon: str = ""   # Optional icon identifier
    parent: str = "" # Parent tab group


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

    def __init__(self, bot: BarkBot) -> None:
        self.bot = bot
        self.enabled: bool = False
        self._logger = logging.getLogger(f"bark.modules.{self.name}")

    # ── Lifecycle ─────────────────────────────────────

    @abc.abstractmethod
    async def enable(self) -> None:
        """Called when the module is enabled. Register commands and events here."""
        ...

    @abc.abstractmethod
    async def disable(self) -> None:
        """Called when the module is disabled. Unregister everything here."""
        ...

    async def reload(self) -> None:
        """Disable then re-enable the module."""
        self._logger.info("Reloading module '%s'", self.name)
        await self.disable()
        await self.enable()
        self._logger.info("Module '%s' reloaded", self.name)

    # ── Registration helpers ──────────────────────────

    def get_settings_schema(self) -> dict[str, Any]:
        """
        Return JSON Schema for this module's configuration.
        Used by the dashboard to render config forms.
        """
        return {}

    def get_dashboard_pages(self) -> list[PageRegistration]:
        """Return dashboard page registrations."""
        return []

    def get_commands(self) -> list[CommandRegistration]:
        """Return Discord command registrations."""
        return []

    def get_events(self) -> list[EventRegistration]:
        """Return event listener registrations."""
        return []

    def get_permissions(self) -> list[PermissionDefinition]:
        """Return permission definitions."""
        return []

    def get_api_routes(self) -> APIRouter | None:
        """Return a FastAPI APIRouter for module-specific API endpoints."""
        return None

    def get_dashboard_template_vars(self, guild_id: int) -> dict[str, Any]:
        """Return template variables for module dashboard pages."""
        return {}

    # ── Helpers ───────────────────────────────────────

    def log(self, level: str, msg: str, **kwargs) -> None:
        getattr(self._logger, level, self._logger.info)(msg, **kwargs)

    def __repr__(self) -> str:
        return f"<BarkModule name='{self.name}' v{self.version} enabled={self.enabled}>"
