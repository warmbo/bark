from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from database.engine import session_scope
from database.models.guild import Guild
from database.models.voice import VoiceSession
from services.module_manager import ModuleManager


class _Bot:
    def __init__(self, guild) -> None:
        self.guilds = [guild]
        self.tree = MagicMock()


@pytest.mark.asyncio
async def test_voice_event_subscription_persists_join_and_leave(db):
    """Exercise Discord payload -> EventBus guard -> moderation -> SQLite."""
    guild_id = 987654321
    user_id = 123456789
    channel_id = 456789123
    second_channel_id = 456789124
    guild = SimpleNamespace(id=guild_id)

    async with session_scope() as session:
        session.add(
            Guild(
                discord_id=str(guild_id),
                name="Voice test guild",
                owner_id="1",
            )
        )

    manager = ModuleManager(_Bot(guild))  # type: ignore[arg-type]
    manager.discover()
    manager.load_guild_states([(guild_id, "moderation", True)])
    assert await manager.enable_module("moderation")
    assert manager.event_bus.subscriber_count("voice_state_change") == 1

    member = SimpleNamespace(id=user_id, guild=guild)
    channel = SimpleNamespace(id=channel_id, name="Voice test channel")
    second_channel = SimpleNamespace(
        id=second_channel_id, name="Second voice test channel"
    )
    disconnected = SimpleNamespace(channel=None)
    connected = SimpleNamespace(channel=channel)
    moved = SimpleNamespace(channel=second_channel)

    try:
        await manager.event_bus.emit(
            "voice_state_change",
            member=member,
            before=disconnected,
            after=connected,
        )
        # Separate move/leave sessions force SQLite to deserialize the stored
        # joined_at values (without tzinfo) before duration calculation.
        await manager.event_bus.emit(
            "voice_state_change",
            member=member,
            before=connected,
            after=moved,
        )
        await manager.event_bus.emit(
            "voice_state_change",
            member=member,
            before=moved,
            after=disconnected,
        )

        async with session_scope() as session:
            records = (
                await session.execute(
                    select(VoiceSession).where(
                        VoiceSession.guild_id == str(guild_id),
                        VoiceSession.user_id == str(user_id),
                    )
                )
            ).scalars().all()

        assert len(records) == 2
        assert {record.channel_id for record in records} == {
            str(channel_id),
            str(second_channel_id),
        }
        for record in records:
            assert record.left_at is not None
            assert record.duration_seconds is not None
            assert record.duration_seconds >= 0
    finally:
        await manager.disable_all()
