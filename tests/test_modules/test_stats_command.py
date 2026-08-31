"""Command-level tests for `/bark stats` (help module)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from database.engine import session_scope


class _FakeMember:
    def __init__(self, id_, name):
        self.id = id_
        self.name = name
        self.display_name = name
        self.display_avatar = MagicMock()
        self.mention = f"<@{id_}>"


async def _seed(guild_id="1"):
    from database.models.analytics import DailyChannelStat, VoiceGameStat
    from database.models.guild import Guild
    from database.models.reputation import ReputationEvent, ReputationProfile
    from database.models.voice import VoiceSession

    now = datetime.now(timezone.utc)
    async with session_scope() as session:
        session.add(Guild(discord_id=guild_id, name="War Lab"))
        await session.flush()
        session.add(
            DailyChannelStat(
                guild_id=str(guild_id), stat_date=now.date(), channel_id="c1",
                channel_name="general", message_count=50,
            )
        )
        session.add(
            VoiceGameStat(guild_id=str(guild_id), game_name="Minecraft", recorded_at=now)
        )
        session.add(
            ReputationProfile(
                guild_id=str(guild_id), user_id="u1", total_score=100.0, level=5,
                week_start=now.date(), month_start=now.date(),
            )
        )
        session.add(
            ReputationEvent(
                guild_id=str(guild_id), actor_id="a1", event_type="thanks", points=40,
                created_at=now,
            )
        )
        session.add(
            VoiceSession(
                guild_id=str(guild_id), user_id="u1", user_tag="Alice",
                channel_id="vc1", channel_name="hangout",
                joined_at=now, left_at=now, duration_seconds=3600,
            )
        )
        await session.commit()


@pytest.fixture
def interaction():
    interaction = MagicMock()
    interaction.guild = MagicMock()
    interaction.guild.id = 1
    interaction.guild.name = "War Lab"
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _make_stats_cmd():
    from modules.help.module import HelpModule

    return HelpModule(MagicMock())._make_stats_command()


async def _invoke(cmd, interaction, **kwargs):
    await cmd.callback(interaction, **kwargs)


@pytest.mark.asyncio
async def test_stats_command_builds_embed_with_all_fields(db, interaction):
    from modules.help.module import HelpModule

    await _seed()
    cmd = _make_stats_cmd()
    await _invoke(cmd, interaction, public=False)

    interaction.response.defer.assert_awaited_once()
    send = interaction.followup.send
    send.assert_awaited_once()
    embed = send.await_args.kwargs["embed"]
    assert "Activity Stats" in embed.title
    # Layout is a balanced grid: 6 inline fields in two rows of 3, not a tall
    # column of full-width fields.
    fields = embed.fields
    assert len(fields) == 6
    assert all(f.inline for f in fields), "stats fields should be inline (side-by-side)"
    field_names = [f.name for f in fields]
    joined = " ".join(field_names)
    for name in ("Top Channels", "Top Games", "Highest Rep", "Top Voice", "Voice Sessions", "Rep Source"):
        assert name in joined
    # Ranked entries use clean 1./2./3. numbering.
    values = " ".join(f.value for f in fields)
    assert "`1.`" in values
    # Private by default -> ephemeral.
    assert send.await_args.kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_stats_command_public_flag_posts_publicly(db, interaction):
    await _seed()
    cmd = _make_stats_cmd()
    await _invoke(cmd, interaction, public=True)
    send = interaction.followup.send
    assert send.await_args.kwargs["ephemeral"] is False


@pytest.mark.asyncio
async def test_stats_command_empty_guild_shows_no_data_placeholders(db, interaction):
    """A fresh guild with no data renders 'No ... data yet.' placeholders."""
    cmd = _make_stats_cmd()
    await _invoke(cmd, interaction, public=False)
    send = interaction.followup.send
    assert send.await_args.kwargs["embed"].title.startswith("📊")
    field_values = " ".join(f.value for f in send.await_args.kwargs["embed"].fields)
    assert "No message data yet." in field_values
    assert "No reputation data yet." in field_values
