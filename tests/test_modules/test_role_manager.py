"""Tests for the role manager module — rule persistence and event-driven assignment."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from database.engine import session_scope
from database.models.guild import Guild
from database.models.role_manager import RoleAssignment, RoleRule
from services.module_manager import ModuleManager


class _Bot:
    def __init__(self, guild) -> None:
        self.guilds = [guild]
        self.tree = MagicMock()

    def get_guild(self, guild_id):
        return next((g for g in self.guilds if int(g.id) == int(guild_id)), None)


async def _seed_guild(guild_id: int, name: str = "Role test guild") -> None:
    async with session_scope() as session:
        session.add(Guild(discord_id=str(guild_id), name=name, owner_id="1"))


async def _seed_rule(guild_id: int, **fields) -> RoleRule:
    async with session_scope() as session:
        rule = RoleRule(guild_id=str(guild_id), **fields)
        session.add(rule)
        await session.flush()
        rule_id = rule.id
    async with session_scope() as session:
        return (await session.execute(select(RoleRule).where(RoleRule.id == rule_id))).scalar_one()


class _Role(SimpleNamespace):
    """Minimal stand-in for discord.Role supporting hierarchy comparison."""

    def __ge__(self, other):
        return self.position >= getattr(other, "position", 0)

    def __le__(self, other):
        return self.position <= getattr(other, "position", 0)


def _make_guild(guild_id: int):
    role = _Role(id=1001, name="Member", position=10)
    bot_member = SimpleNamespace(id=999, top_role=_Role(id=998, name="Bot", position=20))
    guild = SimpleNamespace(
        id=guild_id,
        name="Role test guild",
        me=bot_member,
        members=[],
        get_role=lambda rid: role if int(rid) == role.id else None,
        get_member=lambda uid: next((m for m in guild.members if int(m.id) == int(uid)), None),
    )
    return guild, role


@pytest.mark.asyncio
async def test_rule_crud_persists_and_lists(db):
    guild_id = 987654321
    await _seed_guild(guild_id)
    guild, _ = _make_guild(guild_id)
    manager = ModuleManager(_Bot(guild))  # type: ignore[arg-type]
    manager.discover()
    manager.load_guild_states([(guild_id, "role_manager", True)])
    assert await manager.enable_module("role_manager")

    async with session_scope() as session:
        session.add(
            RoleRule(
                guild_id=str(guild_id),
                name="Welcome role",
                rule_type="welcome",
                role_id="1001",
                trigger_key="",
                trigger_config="{}",
            )
        )
        session.add(
            RoleRule(
                guild_id=str(guild_id),
                name="30-day member",
                rule_type="tenure",
                role_id="1001",
                trigger_key="tenure:30",
                trigger_config='{"days_required": 30}',
            )
        )

    module = manager.get_all_modules()["role_manager"]
    rules = await module._get_rules(guild_id, ttl=0)
    assert len(rules) == 2
    assert {r.rule_type for r in rules} == {"welcome", "tenure"}


@pytest.mark.asyncio
async def test_voice_rule_adds_on_join_and_removes_on_leave(db):
    guild_id = 987654322
    user_id = 111111111
    await _seed_guild(guild_id)
    guild, role = _make_guild(guild_id)
    manager = ModuleManager(_Bot(guild))  # type: ignore[arg-type]
    manager.discover()
    manager.load_guild_states([(guild_id, "role_manager", True)])
    assert await manager.enable_module("role_manager")

    await _seed_rule(
        guild_id,
        name="Voice role",
        rule_type="voice",
        role_id=str(role.id),
        trigger_key="",
        trigger_config="{}",
        remove_when_inactive=True,
    )

    member = SimpleNamespace(id=user_id, guild=guild, roles=[], bot=False)
    member.add_roles = AsyncMock(side_effect=lambda *a, **kw: member.roles.append(role))
    member.remove_roles = AsyncMock(side_effect=lambda *a, **kw: member.roles.remove(role))

    channel = SimpleNamespace(id=5001, name="General")
    disconnected = SimpleNamespace(channel=None)
    connected = SimpleNamespace(channel=channel)

    await manager.event_bus.emit(
        "discord_voice_state",
        member=member,
        before=disconnected,
        after=connected,
        before_channel=None,
        after_channel=channel,
    )
    member.add_roles.assert_awaited_once_with(role, reason="In voice chat")

    await manager.event_bus.emit(
        "discord_voice_state",
        member=member,
        before=connected,
        after=disconnected,
        before_channel=channel,
        after_channel=None,
    )
    member.remove_roles.assert_awaited_once_with(role, reason="Left voice chat")

    async with session_scope() as session:
        rows = (await session.execute(select(RoleAssignment))).scalars().all()
    assert len(rows) == 2
    assert [r.action for r in rows] == ["add", "remove"]


@pytest.mark.asyncio
async def test_welcome_rule_assigns_on_join(db):
    guild_id = 987654323
    user_id = 222222222
    await _seed_guild(guild_id)
    guild, role = _make_guild(guild_id)
    manager = ModuleManager(_Bot(guild))  # type: ignore[arg-type]
    manager.discover()
    manager.load_guild_states([(guild_id, "role_manager", True)])
    assert await manager.enable_module("role_manager")

    await _seed_rule(
        guild_id,
        name="Welcome role",
        rule_type="welcome",
        role_id=str(role.id),
        trigger_key="",
        trigger_config="{}",
    )

    member = SimpleNamespace(id=user_id, guild=guild, roles=[], bot=False)
    member.add_roles = AsyncMock()

    await manager.event_bus.emit("discord_member_join", member=member)
    member.add_roles.assert_awaited_once_with(role, reason="Welcome role")

    async with session_scope() as session:
        rows = (await session.execute(select(RoleAssignment))).scalars().all()
    assert len(rows) == 1
    assert rows[0].action == "add"
    assert rows[0].user_id == str(user_id)


@pytest.mark.asyncio
async def test_reaction_rule_claim_and_release(db):
    guild_id = 987654324
    user_id = 333333333
    await _seed_guild(guild_id)
    guild, role = _make_guild(guild_id)
    manager = ModuleManager(_Bot(guild))  # type: ignore[arg-type]
    manager.discover()
    manager.load_guild_states([(guild_id, "role_manager", True)])
    assert await manager.enable_module("role_manager")

    await _seed_rule(
        guild_id,
        name="Game ping",
        rule_type="reaction",
        role_id=str(role.id),
        trigger_key="reaction:6001:🎮",
        trigger_config='{"channel_id": "6001", "emoji": "🎮"}',
        remove_when_inactive=True,
    )

    member = SimpleNamespace(id=user_id, guild=guild, roles=[], bot=False)
    member.add_roles = AsyncMock(side_effect=lambda *a, **kw: member.roles.append(role))
    member.remove_roles = AsyncMock(side_effect=lambda *a, **kw: member.roles.remove(role))
    guild.members.append(member)

    emoji = SimpleNamespace(name="🎮", id=None)
    emoji.is_unicode_emoji = lambda: True
    payload = SimpleNamespace(
        guild_id=str(guild_id),
        channel_id=6001,
        message_id=7001,
        user_id=user_id,
        emoji=emoji,
    )

    await manager.event_bus.emit("raw_reaction_add", payload=payload)
    member.add_roles.assert_awaited_once_with(role, reason="Claimed via reaction")

    await manager.event_bus.emit("raw_reaction_remove", payload=payload)
    member.remove_roles.assert_awaited_once_with(role, reason="Released via reaction")

    async with session_scope() as session:
        rows = (await session.execute(select(RoleAssignment))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_reaction_rule_scoped_to_message_id(db):
    """A rule with message_id must ignore reactions on other messages."""
    guild_id = 987654330
    user_id = 555555555
    await _seed_guild(guild_id)
    guild, role = _make_guild(guild_id)
    manager = ModuleManager(_Bot(guild))  # type: ignore[arg-type]
    manager.discover()
    manager.load_guild_states([(guild_id, "role_manager", True)])
    assert await manager.enable_module("role_manager")

    await _seed_rule(
        guild_id,
        name="Pinned game ping",
        rule_type="reaction",
        role_id=str(role.id),
        trigger_key="reaction:6001:🎮",
        trigger_config='{"channel_id": "6001", "message_id": "7001", "emoji": "🎮"}',
        remove_when_inactive=True,
    )

    member = SimpleNamespace(id=user_id, guild=guild, roles=[], bot=False)
    member.add_roles = AsyncMock()
    member.remove_roles = AsyncMock()
    guild.members.append(member)

    emoji = SimpleNamespace(name="🎮", id=None)
    emoji.is_unicode_emoji = lambda: True

    wrong_message = SimpleNamespace(
        guild_id=str(guild_id),
        channel_id=6001,
        message_id=9999,
        user_id=user_id,
        emoji=emoji,
    )
    right_message = SimpleNamespace(
        guild_id=str(guild_id),
        channel_id=6001,
        message_id=7001,
        user_id=user_id,
        emoji=emoji,
    )

    await manager.event_bus.emit("raw_reaction_add", payload=wrong_message)
    member.add_roles.assert_not_awaited()

    await manager.event_bus.emit("raw_reaction_add", payload=right_message)
    member.add_roles.assert_awaited_once_with(role, reason="Claimed via reaction")

    async with session_scope() as session:
        rows = (await session.execute(select(RoleAssignment))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_reaction_rule_matches_custom_emoji_by_id(db):
    """Custom server emoji spec <:name:id> matches by emoji id."""
    guild_id = 987654331
    user_id = 666666666
    await _seed_guild(guild_id)
    guild, role = _make_guild(guild_id)
    manager = ModuleManager(_Bot(guild))  # type: ignore[arg-type]
    manager.discover()
    manager.load_guild_states([(guild_id, "role_manager", True)])
    assert await manager.enable_module("role_manager")

    await _seed_rule(
        guild_id,
        name="Game role",
        rule_type="reaction",
        role_id=str(role.id),
        trigger_key="reaction:6001:123456789012345678",
        trigger_config='{"channel_id": "6001", "emoji": "<:game:123456789012345678>"}',
        remove_when_inactive=True,
    )

    member = SimpleNamespace(id=user_id, guild=guild, roles=[], bot=False)
    member.add_roles = AsyncMock()
    guild.members.append(member)

    emoji = SimpleNamespace(name="game", id=123456789012345678)
    emoji.is_unicode_emoji = lambda: False
    payload = SimpleNamespace(
        guild_id=str(guild_id),
        channel_id=6001,
        message_id=7001,
        user_id=user_id,
        emoji=emoji,
    )

    await manager.event_bus.emit("raw_reaction_add", payload=payload)
    member.add_roles.assert_awaited_once_with(role, reason="Claimed via reaction")


def test_is_twitch_live_only_matches_twitch():
    import discord

    from modules.role_manager.module import _is_twitch_live

    streaming = discord.ActivityType.streaming
    playing = discord.ActivityType.playing

    twitch = SimpleNamespace(type=streaming, platform="twitch", url="https://www.twitch.tv/foo")
    youtube = SimpleNamespace(
        type=streaming, platform="youtube", url="https://www.youtube.com/watch?v=abc"
    )
    custom = SimpleNamespace(type=streaming, platform=None, url="https://custom.stream/bar")
    not_streaming = SimpleNamespace(
        type=playing, platform="twitch", url="https://www.twitch.tv/foo"
    )

    assert _is_twitch_live([twitch]) is True
    # URL pointing at twitch.tv still counts even if platform is missing.
    assert (
        _is_twitch_live(
            [SimpleNamespace(type=streaming, platform=None, url="https://twitch.tv/foo")]
        )
        is True
    )
    assert _is_twitch_live([youtube]) is False
    assert _is_twitch_live([custom]) is False
    # A Twitch platform is irrelevant unless the activity is actually streaming.
    assert _is_twitch_live([not_streaming]) is False
    assert _is_twitch_live([]) is False


def test_parse_emoji_spec_handles_unicode_and_custom():
    from modules.role_manager.module import _parse_emoji_spec

    assert _parse_emoji_spec("🎮") == {"unicode": "🎮"}
    assert _parse_emoji_spec("123456789012345678") == {"id": "123456789012345678"}
    assert _parse_emoji_spec("<:game:123456789012345678>") == {
        "name": "game",
        "id": "123456789012345678",
    }
    assert _parse_emoji_spec("<a:animated:987654321098765432>") == {
        "name": "animated",
        "id": "987654321098765432",
    }
    assert _parse_emoji_spec("") is None


@pytest.mark.asyncio
async def test_rule_ignored_when_role_missing_or_hierarchy_above_bot(db):
    guild_id = 987654325
    user_id = 444444444
    await _seed_guild(guild_id)
    guild, _ = _make_guild(guild_id)
    # Simulate a role the bot cannot manage (same position as bot top role).
    guild.get_role = lambda rid: SimpleNamespace(id=int(rid), name="Too High", position=20)

    manager = ModuleManager(_Bot(guild))  # type: ignore[arg-type]
    manager.discover()
    manager.load_guild_states([(guild_id, "role_manager", True)])
    assert await manager.enable_module("role_manager")

    await _seed_rule(
        guild_id,
        name="Unmanageable",
        rule_type="welcome",
        role_id="5555",
        trigger_key="",
        trigger_config="{}",
    )

    member = SimpleNamespace(id=user_id, guild=guild, roles=[], bot=False)
    member.add_roles = AsyncMock()

    await manager.event_bus.emit("discord_member_join", member=member)
    member.add_roles.assert_not_awaited()

    async with session_scope() as session:
        rows = (await session.execute(select(RoleAssignment))).scalars().all()
    assert len(rows) == 0
