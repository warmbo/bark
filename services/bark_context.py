"""
BarkContext — controlled interface between modules and the Bark runtime.

Modules must ONLY interact with the system through BarkContext.
All DB operations delegate to the service layer.
"""

from __future__ import annotations

import inspect
import json
import logging
from typing import TYPE_CHECKING

from services.moderation_service import ModerationService

if TYPE_CHECKING:
    from bot.client import BarkBot
    from services.event_bus import EventBus

logger = logging.getLogger("bark.context")

_SERVICE = ModerationService()


async def emit_moderation_case_created(
    event_bus: EventBus,
    *,
    guild_id: int,
    case_id: int,
    action_type: str,
    target_tag: str,
    moderator_tag: str,
    reason: str,
) -> None:
    """Publish the canonical guild-scoped moderation realtime contract."""
    emitted = event_bus.emit(
        "moderation_case_created",
        guild_id=str(guild_id),
        case_id=case_id,
        action_type=action_type,
        target_tag=target_tag,
        moderator_tag=moderator_tag,
        reason=reason,
    )
    if inspect.isawaitable(emitted):
        await emitted


class BarkContext:
    """
    Controlled gateway for module-system interaction.

    Modules receive this via __init__ and use it for all system access.
    All database operations delegate to the service layer.
    """

    def __init__(self, bot: BarkBot, event_bus: EventBus) -> None:
        self._bot = bot
        self._event_bus = event_bus

    # ── Bot access (read-only) ──────────────────────────

    @property
    def bot(self) -> BarkBot:
        return self._bot

    @property
    def guilds(self) -> list:
        return list(self._bot.guilds)

    def get_guild(self, guild_id: int):
        return self._bot.get_guild(guild_id)

    def get_member(self, guild_id: int, user_id: int):
        guild = self.get_guild(guild_id)
        return guild.get_member(user_id) if guild else None

    # ── EventBus access ─────────────────────────────────

    @property
    def events(self) -> EventBus:
        return self._event_bus

    # ── Module config (service-delegated) ───────────────

    async def get_module_config(self, module_name: str, guild_id: int) -> dict:
        from sqlalchemy import select

        from database.engine import session_scope
        from database.models.module import ModuleConfig

        async with session_scope() as session:
            result = await session.execute(
                select(ModuleConfig).where(
                    ModuleConfig.module_name == module_name,
                    ModuleConfig.guild_id == str(guild_id),
                )
            )
            dbc = result.scalar_one_or_none()
            if dbc and dbc.config:
                try:
                    return json.loads(dbc.config)
                except json.JSONDecodeError:
                    return {}
            return {}

    async def save_module_config(self, module_name: str, guild_id: int, config: dict) -> bool:
        from sqlalchemy import select

        from database.engine import session_scope
        from database.models.module import ModuleConfig

        async with session_scope() as session:
            result = await session.execute(
                select(ModuleConfig).where(
                    ModuleConfig.module_name == module_name,
                    ModuleConfig.guild_id == str(guild_id),
                )
            )
            dbc = result.scalar_one_or_none()
            if dbc is None:
                dbc = ModuleConfig(guild_id=str(guild_id), module_name=module_name, enabled=True)
                session.add(dbc)
            dbc.config = json.dumps(config)
            await session.commit()
            return True

    # ── Auto Voice persistent runtime state ─────────────

    async def save_auto_voice_channel(
        self,
        *,
        channel_id: int,
        guild_id: int,
        owner_id: int,
        primary_channel_id: int,
    ) -> None:
        from database.engine import session_scope
        from database.models.auto_voice import AutoVoiceChannel

        async with session_scope() as session:
            await session.merge(
                AutoVoiceChannel(
                    channel_id=str(channel_id),
                    guild_id=str(guild_id),
                    owner_id=str(owner_id),
                    primary_channel_id=str(primary_channel_id),
                )
            )

    async def list_auto_voice_channels(self) -> list:
        from sqlalchemy import select

        from database.engine import session_scope
        from database.models.auto_voice import AutoVoiceChannel

        async with session_scope() as session:
            result = await session.execute(select(AutoVoiceChannel))
            return list(result.scalars().all())

    async def normalize_voice_transition(self, guild_id: int, before_channel, after_channel):
        """Hide Auto Voice's transient join-to-create channel from consumers."""
        config = await self.get_module_config("auto_voice", guild_id)
        primary_id = str(config.get("primary_channel_id") or "")

        def visible(channel):
            if channel is None:
                return None
            is_primary = primary_id and str(getattr(channel, "id", "")) == primary_id
            is_named_trigger = str(getattr(channel, "name", "")).strip().casefold() == "new channel"
            return None if is_primary or is_named_trigger else channel

        return visible(before_channel), visible(after_channel)

    async def delete_auto_voice_channel(self, channel_id: int) -> None:
        from database.engine import session_scope
        from database.models.auto_voice import AutoVoiceChannel

        async with session_scope() as session:
            row = await session.get(AutoVoiceChannel, str(channel_id))
            if row is not None:
                await session.delete(row)

    # ── Service-delegated operations ────────────────────

    async def log_audit(
        self,
        guild_id: int,
        action: str,
        actor_id: str,
        actor_tag: str = "",
        target_id: str | None = None,
        target_tag: str = "",
        details: dict | None = None,
    ) -> None:
        await _SERVICE.log_audit(
            guild_id, action, actor_id, actor_tag, target_id, target_tag, details
        )

    async def create_case(
        self,
        guild_id: int,
        action_type: str,
        target_id: str,
        target_tag: str,
        moderator_id: str,
        moderator_tag: str,
        reason: str,
        duration: int | None = None,
    ) -> int:
        case_number = await _SERVICE.create_case(
            guild_id,
            action_type,
            target_id,
            target_tag,
            moderator_id,
            moderator_tag,
            reason,
            duration,
        )
        await emit_moderation_case_created(
            self.events,
            guild_id=guild_id,
            case_id=case_number,
            action_type=action_type,
            target_tag=target_tag,
            moderator_tag=moderator_tag,
            reason=reason,
        )
        return case_number

    async def add_warning(self, guild_id: int, user_id: str, moderator_id: str, reason: str) -> int:
        return await _SERVICE.add_warning(guild_id, user_id, moderator_id, reason)
