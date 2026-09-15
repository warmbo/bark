"""Moderation command behavior: target notifications, validate-before-act, and
Discord errors that must reach the moderator instead of escaping as an
unhandled interaction.

The gaps these cover were observed in the module: only /warn notified the
target, timeout/kick/ban caught only discord.Forbidden (so a 400 from Discord —
delete_days=9, a 30-day timeout — produced no reply at all), and an empty
auto-seeded ruleset made /automod refuse for guilds that never configured it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from database.engine import session_scope
from database.models.guild import Guild
from database.models.ruleset import RuleSet
from services.module_manager import ModuleManager

GUILD_ID = 221627370375872512


class _Perms:
    ban_members = True
    kick_members = True
    moderate_members = True


class _Followup:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, content=None, **kwargs):
        self.messages.append(content or "")

    @property
    def last(self) -> str:
        return self.messages[-1] if self.messages else ""


class _Response:
    def __init__(self) -> None:
        self.deferred = False

    async def defer(self, *a, **k):
        self.deferred = True

    def is_done(self) -> bool:
        return self.deferred


class _Interaction:
    def __init__(self, guild) -> None:
        self.guild = guild
        self.user = SimpleNamespace(id=999, __str__=lambda self: "mod#999")
        self.response = _Response()
        self.followup = _Followup()


class _Guild:
    id = GUILD_ID
    name = "[ ZENHAWX ]"
    owner_id = 164480121477136385
    me = SimpleNamespace(guild_permissions=_Perms())

    def get_channel(self, channel_id):
        return None

    def get_member(self, member_id):
        return None


class _Bot:
    def __init__(self, guild) -> None:
        self.guilds = [guild]
        self.tree = AsyncMock()
        self.user = SimpleNamespace(id="1", name="bark")


class _DiscordResponse:
    """Minimal stand-in for aiohttp's response inside discord.py exceptions
    (they format ``response.reason`` when the exception is constructed)."""

    status = 403
    reason = "Forbidden"


class _Member:
    """Duck-typed member: records Discord calls + DM in one order log."""

    def __init__(self, calls: list[str], *, dm_error=None) -> None:
        self.id = 42
        self.bot = False
        self.mention = "<@42>"
        self._calls = calls
        self._dm_error = dm_error

    def __str__(self) -> str:  # pragma: no cover - tag text only
        return "target#0042"

    async def send(self, content=None, **kwargs):
        self._calls.append("dm")
        if self._dm_error is not None:
            raise self._dm_error
        return None

    async def ban(self, **kwargs):
        self._calls.append("ban")

    async def kick(self, **kwargs):
        self._calls.append("kick")

    async def timeout(self, until, **kwargs):
        self._calls.append("timeout")


async def _module(db):
    """A real ModuleManager-built moderation module backed by the test DB."""
    async with session_scope() as session:
        session.add(Guild(discord_id=str(GUILD_ID), name="[ ZENHAWX ]"))
        await session.flush()
    guild = _Guild()
    manager = ModuleManager(_Bot(guild))  # type: ignore[arg-type]
    manager.discover()
    manager.load_guild_states([(guild.id, "moderation", True)])
    assert await manager.enable_module("moderation")
    return manager.get_module("moderation")


@pytest.mark.asyncio
async def test_timeout_rejects_a_duration_discord_would_400(db):
    module = await _module(db)
    calls: list[str] = []
    member = _Member(calls)
    interaction = _Interaction(_Guild())

    await module._cmd_timeout(interaction, member, 30, "days", "spamming")

    assert "timeout" not in calls, "Discord's API would reject this"
    assert "28 days" in interaction.followup.last


@pytest.mark.asyncio
async def test_timeout_rejects_a_zero_duration(db):
    module = await _module(db)
    calls: list[str] = []
    interaction = _Interaction(_Guild())

    await module._cmd_timeout(interaction, _Member(calls), 0, "minutes", "spamming")

    assert "timeout" not in calls
    assert "greater than zero" in interaction.followup.last


@pytest.mark.asyncio
async def test_timeout_rejects_an_unknown_unit_instead_of_guessing(db):
    """An unrecognised unit silently became "minutes" before this."""
    module = await _module(db)
    calls: list[str] = []
    interaction = _Interaction(_Guild())

    await module._cmd_timeout(interaction, _Member(calls), 30, "fortnights", "spam")

    assert "timeout" not in calls
    assert "Unknown unit" in interaction.followup.last


@pytest.mark.asyncio
async def test_ban_rejects_pruning_beyond_seven_days(db):
    module = await _module(db)
    calls: list[str] = []
    interaction = _Interaction(_Guild())

    await module._cmd_ban(interaction, _Member(calls), "raid", 9)

    assert "ban" not in calls, "Discord's API would reject delete_message_days=9"
    assert "0–7 days" in interaction.followup.last


@pytest.mark.asyncio
async def test_ban_notifies_before_banning_and_reports_pruning(db):
    """The DM must go out first — after a ban the bot cannot message the user."""
    module = await _module(db)
    calls: list[str] = []
    interaction = _Interaction(_Guild())

    await module._cmd_ban(interaction, _Member(calls), "raiding", 3)

    assert calls[:2] == ["dm", "ban"], f"DM must precede the ban, got {calls}"
    assert "pruned 3d" in interaction.followup.last
    assert "Case #" in interaction.followup.last


@pytest.mark.asyncio
async def test_kick_still_kicks_when_the_target_has_dms_closed(db):
    module = await _module(db)
    calls: list[str] = []
    member = _Member(calls, dm_error=discord.Forbidden(_DiscordResponse(), "closed"))
    interaction = _Interaction(_Guild())

    await module._cmd_kick(interaction, member, "cooling off")

    assert calls == ["dm", "kick"], "a closed DM must never block the kick"
    assert "Kicked" in interaction.followup.last


@pytest.mark.asyncio
async def test_discord_http_error_reaches_the_moderator(db):
    """A 400 from Discord used to escape as an unhandled interaction."""
    module = await _module(db)

    class _Erroring(_Member):
        async def kick(self, **kwargs):
            raise discord.HTTPException(_DiscordResponse(), "boom")

    interaction = _Interaction(_Guild())
    await module._cmd_kick(interaction, _Erroring([]), "no reason given")

    assert "Discord rejected the kick" in interaction.followup.last


@pytest.mark.asyncio
async def test_timeout_notifies_target_with_expiry(db):
    module = await _module(db)
    calls: list[str] = []
    interaction = _Interaction(_Guild())

    await module._cmd_timeout(interaction, _Member(calls), 10, "minutes", "spam")

    assert calls == ["timeout", "dm"], "timeout is applied first, then notified"
    assert "until" in interaction.followup.last


@pytest.mark.asyncio
async def test_rule_simulator_reports_a_real_match(db):
    """The simulator runs the production matcher, not a decorative message."""
    module = await _module(db)

    verdict = await module.simulate_rule(
        _Guild(), "invite", {"threshold": 1, "action": "delete"}, "join discord.gg/abc123 now"
    )

    assert "WOULD TRIGGER" in verdict
    assert "Invite link" in verdict
    assert "Nothing was executed" in verdict


@pytest.mark.asyncio
async def test_rule_simulator_reports_a_non_match(db):
    module = await _module(db)

    verdict = await module.simulate_rule(
        _Guild(), "invite", {"threshold": 1, "action": "delete"}, "just saying hello everyone"
    )

    assert "would NOT trigger" in verdict


@pytest.mark.asyncio
async def test_rule_simulator_refuses_to_claim_a_verdict_for_stateful_rules(db):
    """mention_rate spans messages; claiming "would NOT trigger" would be a lie
    about a rule that cannot be evaluated from one message."""
    module = await _module(db)

    verdict = await module.simulate_rule(
        _Guild(), "mention_rate", {"threshold": 5, "window_seconds": 30}, "hi"
    )

    assert "stateful, cross-message" in verdict
    assert "WOULD" not in verdict
    assert "would NOT trigger" not in verdict


@pytest.mark.asyncio
async def test_rule_simulator_never_executes_the_effect(db):
    """A simulation must not delete, warn, time out or open a case."""
    from sqlalchemy import func, select

    from database.models.moderation import ModerationCase

    module = await _module(db)

    verdict = await module.simulate_rule(
        _Guild(), "spam", {"threshold": 1, "window_seconds": 10, "action": "timeout"}, "spam"
    )

    assert "WOULD TRIGGER" in verdict
    async with session_scope() as session:
        cases = (
            await session.execute(
                select(func.count(ModerationCase.id)).where(
                    ModerationCase.guild_id == str(GUILD_ID)
                )
            )
        ).scalar()
    assert cases == 0, "simulation must not open a case"


@pytest.mark.asyncio
async def test_no_empty_ruleset_is_seeded_when_there_is_no_legacy_config(db):
    """An auto-seeded empty ruleset made /automod refuse for unconfigured guilds."""
    module = await _module(db)

    created = await module._ensure_default_ruleset(GUILD_ID)

    assert created is False
    async with session_scope() as session:
        from sqlalchemy import func, select

        count = (
            await session.execute(
                select(func.count(RuleSet.id)).where(RuleSet.guild_id == str(GUILD_ID))
            )
        ).scalar()
    assert count == 0, "nothing to migrate means nothing to seed"


@pytest.mark.asyncio
async def test_automod_keeps_working_when_the_only_ruleset_is_empty(db):
    """The legacy path must survive an empty ruleset (previously a dead end)."""
    module = await _module(db)
    async with session_scope() as session:
        session.add(RuleSet(guild_id=str(GUILD_ID), name="Default", enabled=True, priority=100))
        await session.commit()
    interaction = _Interaction(_Guild())

    await module._cmd_automod(interaction, "spam", True, 5, "delete")

    assert "Ruleset system" not in interaction.followup.last
    assert interaction.followup.messages, "the legacy path must answer"
