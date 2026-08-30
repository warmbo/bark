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
        ("Channel", f"#{managed.name}", True),
    ]


@pytest.mark.asyncio
async def test_voice_leave_log_records_channel_name_not_mention():
    """A deleted Auto Voice channel must not degrade the leave log to
    '#deleted-channel' — the embed records the name as it was."""
    guild_id = 221627370375872512
    managed = SimpleNamespace(id=200, name="hangout", mention="<#200>")
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
    ctx.get_module_config = AsyncMock(return_value={})
    module = LoggingModule(ctx)
    module._get_channel = AsyncMock(return_value=SimpleNamespace())
    module._send = AsyncMock()

    await module._on_voice_state(
        "discord_voice_state",
        member=member,
        before=SimpleNamespace(channel=managed),
        after=SimpleNamespace(channel=None),
    )

    module._send.assert_awaited_once()
    args = module._send.await_args.args
    assert args[1] == "🔇 Voice Leave"
    assert module._send.await_args.kwargs["fields"] == [
        ("User", f"{member} ({member.id})", True),
        ("Channel", "#hangout", True),
    ]


@pytest.mark.asyncio
async def test_logging_uses_original_channel_snapshot_when_voice_state_is_mutated():
    guild = SimpleNamespace(id=10)
    member = SimpleNamespace(
        id=42,
        guild=guild,
        mention="<@42>",
        bot=False,
    )
    primary = SimpleNamespace(id=100, name="new channel", mention="<#100>")
    managed = SimpleNamespace(id=200, name="hangout", mention="<#200>")
    before = SimpleNamespace(channel=None)
    after = SimpleNamespace(channel=managed)

    ctx = BarkContext(SimpleNamespace(), EventBus())
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
        before=before,
        after=after,
        before_channel=None,
        after_channel=primary,
    )

    module._send.assert_not_awaited()


@pytest.mark.asyncio
async def test_member_and_voice_events_persist_to_shared_audit_store():
    """Item 7: member join/leave and voice transitions must be written to the
    shared audit-log store (not just posted as embeds) so they surface in the
    dashboard Recent Activity feed and the Logging module's own log view."""
    guild = SimpleNamespace(id=221627370375872512, member_count=100)
    member = SimpleNamespace(
        id=42,
        guild=guild,
        mention="<@42>",
        display_avatar=SimpleNamespace(url="https://x/a.png"),
        created_at=MagicMock(),
        __str__=lambda self: "cody#0000",
    )
    channel = SimpleNamespace(id=100, name="hangout", mention="<#100>")

    ctx = BarkContext(SimpleNamespace(), EventBus())
    ctx.log_audit = AsyncMock()
    ctx.normalize_voice_transition = AsyncMock(
        side_effect=lambda _gid, before_ch, after_ch: (before_ch, after_ch)
    )
    module = LoggingModule(ctx)
    module._get_channel = AsyncMock(return_value=SimpleNamespace())
    module._send = AsyncMock()

    # Member join
    await module._on_member_join("discord_member_join", member=member)
    # Member leave
    await module._on_member_remove("discord_member_remove", member=member)
    # Voice join
    await module._on_voice_state(
        "discord_voice_state",
        member=member,
        before=SimpleNamespace(channel=None),
        after=SimpleNamespace(channel=channel),
        before_channel=None,
        after_channel=channel,
    )

    calls = [c for c in ctx.log_audit.await_args_list]
    actions = [c.args[1] for c in calls]
    assert "member_join" in actions
    assert "member_leave" in actions
    assert "voice_join" in actions
    # Voice join carries the channel name in details for the log view.
    voice_call = next(c for c in calls if c.args[1] == "voice_join")
    assert voice_call.kwargs.get("details") == {"channel": "#hangout"}


@pytest.mark.asyncio
async def test_noop_same_channel_move_is_suppressed():
    """A voice-state event with from == to channel (a no-op move) must not be
    logged — it is not a real transition and only contributes to spam."""
    guild_id = 221627370375872512
    channel = SimpleNamespace(id=200, name="hangout", mention="<#200>")
    guild = SimpleNamespace(id=guild_id)
    member = SimpleNamespace(
        id=42,
        guild=guild,
        mention="<@42>",
        __str__=lambda self: "cody",
    )
    bot = MagicMock()
    bot.get_guild.return_value = guild
    ctx = BarkContext(bot, EventBus())
    ctx.get_module_config = AsyncMock(return_value={})
    module = LoggingModule(ctx)
    module._get_channel = AsyncMock(return_value=SimpleNamespace())
    module._send = AsyncMock()

    await module._on_voice_state(
        "discord_voice_state",
        member=member,
        before=SimpleNamespace(channel=channel),
        after=SimpleNamespace(channel=channel),
    )

    module._send.assert_not_awaited()


@pytest.mark.asyncio
async def test_rapid_duplicate_voice_events_are_debounced():
    """Auto Voice's join->move->cleanup cycle can fire several on_voice_state
    events for the same member within a second. Rapid duplicate transitions for
    one member must be collapsed so a single move does not flood the log."""
    import services.logging_voice_debounce as debounce

    debounce.reset()
    guild_id = 221627370375872512
    guild = SimpleNamespace(id=guild_id)
    member = SimpleNamespace(
        id=42,
        guild=guild,
        mention="<@42>",
        __str__=lambda self: "cody",
    )
    a = SimpleNamespace(id=100, name="hangout", mention="<#100>")
    b = SimpleNamespace(id=200, name="afk channel", mention="<#200>")

    bot = MagicMock()
    bot.get_guild.return_value = guild
    ctx = BarkContext(bot, EventBus())
    ctx.get_module_config = AsyncMock(return_value={})
    module = LoggingModule(ctx)
    module._get_channel = AsyncMock(return_value=SimpleNamespace())
    module._send = AsyncMock()

    # A real move a -> b, followed by a rapid duplicate (same member, same
    # transition) within the debounce window. Only the first should be logged.
    await module._on_voice_state(
        "discord_voice_state",
        member=member,
        before=SimpleNamespace(channel=a),
        after=SimpleNamespace(channel=b),
    )
    await module._on_voice_state(
        "discord_voice_state",
        member=member,
        before=SimpleNamespace(channel=a),
        after=SimpleNamespace(channel=b),
    )

    module._send.assert_awaited_once()
    debounce.reset()
