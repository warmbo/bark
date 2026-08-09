"""Tests for AutoMod edited-message scoping (check_new_messages /
check_edited_messages were stored + editable but never enforced)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from database.engine import session_scope
from database.models.guild import Guild
from database.models.ruleset import Rule, RuleSet
from services.module_manager import ModuleManager


class _Bot:
    def __init__(self, guild) -> None:
        self.guilds = [guild]
        self.tree = AsyncMock()
        self.user = SimpleNamespace(id="1", name="bark")


class _Guild:
    id = 221627370375872512
    name = "[ ZENHAWX ]"
    owner_id = 164480121477136385

    def get_channel(self, channel_id):
        return None

    def get_member(self, member_id):
        return None


def _msg(content: str, guild):
    return SimpleNamespace(
        id=123,
        content=content,
        webhook_id=None,
        author=SimpleNamespace(
            id=100, bot=False, name="raider", roles=[], created_at=None, joined_at=None
        ),
        guild=guild,
        channel=SimpleNamespace(id=2, mention="#general", category_id=None),
        delete=AsyncMock(),
        attachments=[],
        mentions=[],
        role_mentions=[],
        mention_everyone=False,
        created_at=None,
    )


async def _seed_ruleset(guild_id: str, *, check_new: bool, check_edited: bool):
    async with session_scope() as session:
        session.add(
            Guild(discord_id=str(guild_id), name="[ ZENHAWX ]", owner_id="164480121477136385")
        )
        await session.flush()
        rs = RuleSet(
            guild_id=str(guild_id),
            name="Edit Scope Test",
            enabled=True,
            priority=100,
            check_new_messages=check_new,
            check_edited_messages=check_edited,
        )
        session.add(rs)
        await session.flush()
        session.add(
            Rule(
                ruleset_id=rs.id,
                trigger_type="scam_link",
                trigger_config="{}",
                effect_type="delete",
                effect_config="{}",
                conditions="{}",
                enabled=True,
                priority=50,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_check_new_messages_false_suppresses_new_message_rule(db):
    """A ruleset with check_new_messages=False must NOT fire on new messages."""
    await _seed_ruleset("221627370375872512", check_new=False, check_edited=False)
    guild = _Guild()
    manager = ModuleManager(_Bot(guild))  # type: ignore[arg-type]
    manager.discover()
    manager.load_guild_states([(guild.id, "moderation", True)])
    assert await manager.enable_module("moderation")
    try:
        msg = _msg("free nitro at discord-nitro.xyz", guild)
        await manager.event_bus.emit("discord_message", message=msg)
        msg.delete.assert_not_awaited()
    finally:
        await manager.disable_all()


@pytest.mark.asyncio
async def test_check_edited_messages_true_fires_on_edit(db):
    """A ruleset with check_edited_messages=True must fire when a message is
    edited into a scam — previously the flag was dead config."""
    await _seed_ruleset("221627370375872512", check_new=False, check_edited=True)
    guild = _Guild()
    manager = ModuleManager(_Bot(guild))  # type: ignore[arg-type]
    manager.discover()
    manager.load_guild_states([(guild.id, "moderation", True)])
    assert await manager.enable_module("moderation")
    try:
        before = _msg("hello", guild)
        after = _msg("free nitro at discord-nitro.xyz", guild)
        await manager.event_bus.emit(
            "discord_message_edit", before=before, after=after
        )
        after.delete.assert_awaited_once()
    finally:
        await manager.disable_all()
