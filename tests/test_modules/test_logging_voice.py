from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.logging.module import LoggingModule
from services.bark_context import BarkContext
from services.event_bus import EventBus


@pytest.mark.asyncio
async def test_join_to_create_transition_logs_only_the_final_voice_channel():
    guild_id = 221627370375872512
    primary = SimpleNamespace(id=100, name="new channel", mention="#new-channel")
    managed = SimpleNamespace(id=200, name="hangout", mention="#hangout")
    guild = SimpleNamespace(id=guild_id)
    member = SimpleNamespace(
        id=42,
        guild=guild,
        mention="@cody",
        __str__=lambda self: "cody",
    )
    bot = MagicMock()
    bot.get_guild.return_value = guild
    ctx = BarkContext(bot, EventBus())
    ctx.get_module_config = AsyncMock(
        side_effect=lambda module, _guild_id: (
            {"primary_channel_id": str(primary.id)} if module == "auto_voice" else {}
        )
    )
    module = LoggingModule(ctx)
    module._get_channel = AsyncMock(return_value=SimpleNamespace())
    module._send = AsyncMock()

    await module._on_voice_state(
        "discord_voice_state",
        member=member,
        before=SimpleNamespace(channel=None),
        after=SimpleNamespace(channel=primary),
    )
    await module._on_voice_state(
        "discord_voice_state",
        member=member,
        before=SimpleNamespace(channel=primary),
        after=SimpleNamespace(channel=managed),
    )

    module._send.assert_awaited_once()
    args = module._send.await_args.args
    assert args[1] == "🔊 Voice Join"
    assert module._send.await_args.kwargs["fields"] == [
        ("User", f"{member} ({member.id})", True),
        ("Channel", managed.mention, True),
    ]
