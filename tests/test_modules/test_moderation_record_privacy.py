"""Moderation record privacy: cases/warnings must never broadcast publicly.

`/bark cases` and `/bark warnings` expose *other members'* moderation records —
warning reasons, moderator identities, case targets and reasons. These are
sensitive server-internal records. Even though they are member-readable for
self/private viewing, they must not be postable to the public channel by any
member via a visibility toggle.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest


class _FakeMember:
    def __init__(self, id_, name):
        self.id = id_
        self.name = name
        self.display_name = name
        self.display_avatar = MagicMock()


@pytest.fixture
def interaction():
    interaction = MagicMock()
    interaction.guild = MagicMock()
    interaction.guild.id = 1
    interaction.guild.get_member = lambda uid: None
    interaction.user = _FakeMember(7007, "Member")
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _command(module, name):
    return getattr(module, f"_make_{name}_command")()


async def _invoke(command_obj, interaction, **kwargs):
    await command_obj.callback(interaction, **kwargs)


async def _seed_records(db):
    from database.engine import session_scope
    from database.models.guild import Guild
    from database.models.moderation import ModerationCase, Warning

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="War Lab"))
        case = ModerationCase(
            guild_id="1",
            case_number=1,
            action_type="warn",
            target_id="11",
            target_tag="Alice",
            moderator_id="42",
            moderator_tag="Mod#0000",
            reason="test",
        )
        session.add(case)
        await session.flush()
        session.add(
            Warning(
                guild_id="1",
                case_id=case.id,
                user_id="11",
                moderator_id="42",
                reason="test",
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_cases_always_ephemeral_even_when_hide_false(db, interaction):
    """/bark cases exposes others' moderation records and must always respond
    privately — it has no hide/public-broadcast option."""
    from modules.moderation.module import ModerationModule

    await _seed_records(db)
    cmd = _command(ModerationModule(MagicMock()), "cases")
    # The command no longer accepts a `hide` param; invoking with one must not
    # be possible (the leaf exposes only `limit`). Assert the leaf has no hide.
    names = {p.name for p in cmd.parameters}
    assert "hide" not in names, "cases must not expose a public-broadcast toggle"
    await _invoke(cmd, interaction, limit=10)

    defer_kwargs = interaction.response.defer.await_args.kwargs if interaction.response.defer.await_args else {}
    assert defer_kwargs.get("ephemeral", False) is True, "cases defer must stay ephemeral"
    for call in interaction.followup.send.await_args_list:
        assert call.kwargs.get("ephemeral", False) is True, "cases send must stay ephemeral"


@pytest.mark.asyncio
async def test_warnings_always_ephemeral_even_when_hide_false(db, interaction):
    """/bark warnings exposes another member's warning history and must always
    respond privately — it has no hide/public-broadcast option."""
    from modules.moderation.module import ModerationModule

    await _seed_records(db)
    cmd = _command(ModerationModule(MagicMock()), "warnings")
    names = {p.name for p in cmd.parameters}
    assert "hide" not in names, "warnings must not expose a public-broadcast toggle"
    await _invoke(cmd, interaction, member=_FakeMember(11, "Alice"))

    defer_kwargs = interaction.response.defer.await_args.kwargs if interaction.response.defer.await_args else {}
    assert defer_kwargs.get("ephemeral", False) is True, "warnings defer must stay ephemeral"
    for call in interaction.followup.send.await_args_list:
        assert call.kwargs.get("ephemeral", False) is True, "warnings send must stay ephemeral"
