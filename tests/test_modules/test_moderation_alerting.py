"""Tests for AutoMod alerting — the fan-out that makes triggers visible.

Coverage:
- Webhook scam messages are deleted + alerted (previously skipped entirely
  because webhook authors are bot-flagged).
- _notify_automod writes a persistent dashboard audit entry, DMs the server
  owner, and emits the automod_triggered bus event.
- Join-raid detection alerts the owner.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from database.engine import session_scope
from database.models.guild import Guild
from database.models.moderation import AuditLog
from modules.moderation.module import ModerationModule
from services.event_bus import EventBus
from services.module_manager import ModuleManager


class _Bot:
    def __init__(self, guild) -> None:
        self.guilds = [guild]
        self.tree = AsyncMock()
        self.user = SimpleNamespace(id="1401694499142500414", name="bark")


class _Owner:
    def __init__(self) -> None:
        self.id = 164480121477136385
        self.send = AsyncMock()


class _Guild:
    def __init__(self, guild_id: int, name: str = "Test Guild") -> None:
        self.id = guild_id
        self.name = name
        self.owner_id = 164480121477136385
        self.owner = _Owner()
        self.system_channel = None
        self.me = SimpleNamespace(id=1)

    def get_channel(self, channel_id):
        return None

    def get_member(self, member_id):
        return None


def _webhook_message(guild):
    author = SimpleNamespace(id=999, bot=True, name="spamwebhook")
    return SimpleNamespace(
        id=777,
        webhook_id=888,
        content="free nitro @everyone",
        author=author,
        guild=guild,
        channel=SimpleNamespace(id=2, mention="#general"),
        delete=AsyncMock(),
        attachments=[],
        mentions=[],
        role_mentions=[],
        mention_everyone=False,
        created_at=None,
    )


@pytest.mark.asyncio
async def test_webhook_scam_is_deleted_and_alerted(db):
    """Webhook spam must be deleted AND produce an audit entry + owner DM.
    Regression: webhook authors are bot-flagged, so the old code returned
    before any check — this is the vector that slipped past detection."""
    guild_id = 221627370375872512
    guild = _Guild(guild_id)
    manager = ModuleManager(_Bot(guild))  # type: ignore[arg-type]
    manager.discover()
    manager.load_guild_states([(guild_id, "moderation", True)])
    assert await manager.enable_module("moderation")

    try:
        async with session_scope() as session:
            session.add(
                Guild(
                    discord_id=str(guild_id),
                    name="[ ZENHAWX ]",
                    owner_id=str(guild.owner_id),
                )
            )
            await session.commit()

        msg = _webhook_message(guild)
        await manager.event_bus.emit("discord_message", message=msg)

        msg.delete.assert_awaited_once()

        async with session_scope() as session:
            rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.guild_id == str(guild_id),
                            AuditLog.action == "automod_triggered",
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert rows, "webhook scam must produce a persistent dashboard audit entry"
        assert "Webhook scam" in rows[0].details

        guild.owner.send.assert_awaited_once()
        embed = guild.owner.send.await_args.kwargs["embed"]
        assert "Bark AutoMod Alert" in embed.title
    finally:
        await manager.disable_all()


@pytest.mark.asyncio
async def test_notify_automod_fans_out_to_all_surfaces():
    events = EventBus()
    received = []

    async def _capture(event_type, **kw):
        received.append(kw)

    events.subscribe("automod_triggered", _capture, priority=10)
    ctx = SimpleNamespace(
        events=events,
        bot=SimpleNamespace(user=SimpleNamespace(id="1")),
        log_audit=AsyncMock(),
    )
    module = ModerationModule(ctx)  # type: ignore[arg-type]
    guild = _Guild(221627370375872512)

    await module._notify_automod(
        guild,
        rule="Ruleset:Scam Protection/duplicate_message",
        action="kick",
        user_tag="2y1v",
        content="bro",
        target_id=1493539060801736886,
    )

    # 1. Persistent dashboard audit feed
    ctx.log_audit.assert_awaited_once()
    call = ctx.log_audit.await_args
    assert call.args[0] == guild.id
    assert call.args[1] == "automod_triggered"
    assert call.kwargs["actor_id"] == "1"  # actor = bot
    assert call.kwargs["target_tag"] == "2y1v"
    # 2. Owner DM
    guild.owner.send.assert_awaited_once()
    embed = guild.owner.send.await_args.kwargs["embed"]
    assert embed.title == "🚨 Bark AutoMod Alert"
    # 3. Bus event (drives SSE toast + mod-log channel)
    assert received, "automod_triggered must be emitted on the bus"
    assert received[0]["rule"].endswith("duplicate_message")
    assert received[0]["action"] == "kick"
    assert received[0]["guild_id"] == str(guild.id)


@pytest.mark.asyncio
async def test_automod_kick_creates_moderation_case(db):
    """An automod kick/kick_purge must surface as a real moderation case so it
    shows in Recent Activity and the moderation Cases feed."""
    from sqlalchemy import select

    from database.models.moderation import ModerationCase

    guild_id = 221627370375872512
    async with session_scope() as session:
        session.add(
            Guild(
                discord_id=str(guild_id),
                name="[ ZENHAWX ]",
                owner_id="164480121477136385",
            )
        )
        await session.commit()

    events = EventBus()
    ctx = SimpleNamespace(
        events=events,
        bot=SimpleNamespace(user=SimpleNamespace(id="1401694499142500414")),
        log_audit=AsyncMock(),
    )
    module = ModerationModule(ctx)  # type: ignore[arg-type]
    guild = _Guild(guild_id)

    await module._notify_automod(
        guild,
        rule="Ruleset:Scam Protection/duplicate_message",
        action="kick_purge",
        user_tag="2y1v",
        content="bro",
        target_id=1493539060801736886,
    )

    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(ModerationCase).where(
                        ModerationCase.guild_id == str(guild_id)
                    )
                )
            )
            .scalars()
            .all()
        )
    assert rows, "automod kick must create a moderation case"
    assert rows[0].action_type == "kick"
    assert rows[0].target_tag == "2y1v"
    assert "[AutoMod]" in rows[0].reason


@pytest.mark.asyncio
async def test_join_raid_alerts_owner(db):
    """A join raid (>= threshold joins in window) must DM the owner."""
    guild_id = 221627370375872512
    guild = _Guild(guild_id)
    manager = ModuleManager(_Bot(guild))  # type: ignore[arg-type]
    manager.discover()
    manager.load_guild_states([(guild_id, "moderation", True)])
    assert await manager.enable_module("moderation")

    try:
        async with session_scope() as session:
            session.add(
                Guild(
                    discord_id=str(guild_id),
                    name="[ ZENHAWX ]",
                    owner_id=str(guild.owner_id),
                )
            )
            await session.commit()

        for i in range(5):
            member = SimpleNamespace(
                id=1000 + i,
                bot=False,
                guild=guild,
                mention=f"<@{1000 + i}>",
                name=f"joiner{i}",
            )
            await manager.event_bus.emit("discord_member_join", member=member)

        guild.owner.send.assert_awaited_once()
        embed = guild.owner.send.await_args.kwargs["embed"]
        assert "Raid detected" in embed.title or "Bark AutoMod Alert" in embed.title

        async with session_scope() as session:
            rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.guild_id == str(guild_id),
                            AuditLog.action == "automod_triggered",
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert any("Raid detected" in r.details for r in rows)
    finally:
        await manager.disable_all()
