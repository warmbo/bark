"""Catch-up tier-role sync tests (boot/join recovery for offline-earned levels)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from database.engine import session_scope
from database.models.guild import Guild
from database.models.reputation import ReputationProfile, ReputationTier
from modules.reputation.module import ReputationModule
from services.bark_context import BarkContext


def _fake_bot_with_guild():
    """Bot whose guild returns a recording member for user 99."""
    calls = []

    class FakeMember:
        def __init__(self):
            self.roles = []
            self.id = 99

        async def add_roles(self, role, reason=None):
            calls.append(("add", getattr(role, "id", role)))
            if role not in self.roles:
                self.roles.append(role)

        async def remove_roles(self, role, reason=None):
            calls.append(("remove", getattr(role, "id", role)))
            if role in self.roles:
                self.roles.remove(role)

    member = FakeMember()
    role_scout = SimpleNamespace(id=777, name="Scout Role")
    role_elite = SimpleNamespace(id=888, name="Elite Role")

    guild = SimpleNamespace(
        id=1,
        get_member=lambda uid: member if uid == 99 else None,
        get_role=lambda rid: {777: role_scout, 888: role_elite}.get(rid),
    )
    bot = MagicMock()
    bot.guilds = [guild]
    bot.get_guild.return_value = guild
    return bot, member, role_scout, role_elite, calls


async def _seed(guild_id: str, *, scout_role, elite_role):
    async with session_scope() as session:
        session.add(Guild(discord_id=guild_id, name="Test Guild"))
        session.add(
            ReputationTier(
                guild_id=str(guild_id),
                name="Recruit",
                symbol="⬜",
                min_level=0,
                color_hex="#99aab5",
                sort_order=0,
            )
        )
        session.add(
            ReputationTier(
                guild_id=str(guild_id),
                name="Scout",
                symbol="🥉",
                min_level=10,
                color_hex="#cd7f32",
                role_id=str(scout_role.id),
                assign_role=True,
                sort_order=1,
            )
        )
        if elite_role:
            session.add(
                ReputationTier(
                    guild_id=str(guild_id),
                    name="Elite",
                    symbol="🥇",
                    min_level=30,
                    color_hex="#ffd700",
                    role_id=str(elite_role.id),
                    assign_role=True,
                    sort_order=2,
                )
            )
        await session.commit()


def _profile(total_score: float) -> ReputationProfile:
    from datetime import date, timedelta

    today = date.today()
    return ReputationProfile(
        guild_id="1",
        user_id="99",
        total_score=total_score,
        week_start=today - timedelta(days=today.weekday()),
        month_start=today.replace(day=1),
    )


@pytest.mark.asyncio
async def test_sync_assigns_role_to_member_who_leveled_offline(db):
    bot, member, role_scout, _, _ = _fake_bot_with_guild()
    await _seed("1", scout_role=role_scout, elite_role=None)
    async with session_scope() as session:
        session.add(_profile(total_score=31250.0))  # level 25 → Scout (level-gated)
        await session.commit()

    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    assert await module._sync_tier_roles(1) == 1
    assert role_scout in member.roles


@pytest.mark.asyncio
async def test_sync_skips_members_below_linked_tier(db):
    bot, member, role_scout, _, calls = _fake_bot_with_guild()
    await _seed("1", scout_role=role_scout, elite_role=None)
    async with session_scope() as session:
        session.add(_profile(total_score=100.0))  # level 1 → Recruit (no linked role)
        await session.commit()

    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    assert await module._sync_tier_roles(1) == 0
    assert member.roles == []
    assert calls == []


@pytest.mark.asyncio
async def test_sync_does_not_demote_when_score_drops(db):
    """Roles only go up: a member below the tier threshold keeps their role."""
    bot, member, role_scout, role_elite, calls = _fake_bot_with_guild()
    await _seed("1", scout_role=role_scout, elite_role=role_elite)
    async with session_scope() as session:
        session.add(_profile(total_score=100.0))  # level 1 → Recruit, but member already holds Elite
        await session.commit()

    member.roles.append(role_elite)

    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    assert await module._sync_tier_roles(1) == 0
    assert role_elite in member.roles
    assert calls == []  # nothing removed


@pytest.mark.asyncio
async def test_sync_gives_current_tier_role_not_lower_tier(db):
    """A member at Elite gets the Elite role; lower Scout role is stripped."""
    bot, member, role_scout, role_elite, calls = _fake_bot_with_guild()
    await _seed("1", scout_role=role_scout, elite_role=role_elite)
    async with session_scope() as session:
        session.add(_profile(total_score=60000.0))  # level 34 → Elite
        await session.commit()

    member.roles.append(role_scout)  # stale lower-tier role from an earlier state

    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    assert await module._sync_tier_roles(1) == 1
    assert role_elite in member.roles
    assert role_scout not in member.roles
    assert ("remove", 777) in calls


@pytest.mark.asyncio
async def test_member_join_syncs_tier_role(db):
    """A returning member gets their tier role back after joining."""
    bot, member, role_scout, _, calls = _fake_bot_with_guild()
    await _seed("1", scout_role=role_scout, elite_role=None)
    async with session_scope() as session:
        session.add(_profile(total_score=31250.0))  # level 25 → Scout
        await session.commit()

    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    joined = SimpleNamespace(id=99, bot=False, guild=SimpleNamespace(id=1))

    assert await module._on_member_join("discord_member_join", member=joined) is None
    assert ("add", 777) in calls
    assert role_scout in member.roles


@pytest.mark.asyncio
async def test_member_join_skips_bots(db):
    """Bots joining must not receive tier roles."""
    bot, _, _, _, calls = _fake_bot_with_guild()
    await _seed("1", scout_role=SimpleNamespace(id=777), elite_role=None)

    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    joined = SimpleNamespace(id=99, bot=True, guild=SimpleNamespace(id=1))
    await module._on_member_join("discord_member_join", member=joined)
    assert calls == []


@pytest.mark.asyncio
async def test_import_recomputes_level_and_tier(db):
    """Imported profiles derive level + tier from total_score."""
    from datetime import date

    bot, _, role_scout, role_elite, _ = _fake_bot_with_guild()
    await _seed("1", scout_role=role_scout, elite_role=role_elite)
    async with session_scope() as session:
        session.add(
            ReputationProfile(
                guild_id="1",
                user_id="98",
                total_score=0.0,
                week_start=date.today(),
                month_start=date.today().replace(day=1),
            )
        )
        await session.commit()

    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    result = await module.import_stats(
        1, {"profiles": [{"user_id": "98", "total_score": 60000.0}]}
    )

    assert "restored 1 profile(s)" in result[0]
    async with session_scope() as session:
        from sqlalchemy import select

        prof = (
            await session.execute(
                select(ReputationProfile).where(
                    ReputationProfile.guild_id == "1",
                    ReputationProfile.user_id == "98",
                )
            )
        ).scalar_one()
        assert prof.level == 34  # isqrt(60000/50)
        assert prof.current_tier == "Elite"


@pytest.mark.asyncio
async def test_showoff_mentions_unlocked_role_on_tier_up(db):
    """Promotion announcements name the linked role + channel hint."""
    from types import SimpleNamespace

    sent = []

    class FakeChannel:
        async def send(self, **kwargs):
            sent.append(kwargs)

    member = SimpleNamespace(display_name="Cody", display_avatar=SimpleNamespace(url="http://x/avatar.png"))
    guild = SimpleNamespace(
        get_channel=lambda cid: FakeChannel(),
        get_member=lambda uid: member,
    )
    bot = MagicMock()
    bot.guilds = [guild]
    bot.get_guild.return_value = guild
    bot.modules = MagicMock()
    bot.modules.event_bus = MagicMock()

    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    import modules.reputation.module as rep_module

    real_discord = rep_module.discord
    rep_module.discord = SimpleNamespace(
        Embed=real_discord.Embed,
        Color=real_discord.Color,
        Forbidden=real_discord.Forbidden,
        HTTPException=real_discord.HTTPException,
        TextChannel=FakeChannel,
    )
    try:
        profile = _profile(total_score=31250.0)
        tier_data = {
            "name": "Scout",
            "symbol": "🥉",
            "color_hex": "#cd7f32",
            "role_id": "777",
            "assign_role": True,
        }
        await module._send_showoff(
            guild_id=1,
            user_id=99,
            profile=profile,
            tier_data=tier_data,
            leveled_up=False,
            tier_changed=True,
            new_rewards=[],
            config={"showoff_channel_id": 5},
        )
    finally:
        rep_module.discord = real_discord

    assert sent, "expected a showoff message"
    fields = sent[0]["embed"].fields
    tier_field = next(f for f in fields if "New Tier" in f.name)
    assert "<@&777>" in tier_field.value
    assert "more channels" in tier_field.value
