from types import SimpleNamespace

import pytest

from bot.client import BarkBot


@pytest.mark.asyncio
async def test_voice_transition_channels_are_snapshotted_before_handlers_can_mutate_state():
    primary = SimpleNamespace(id=100, name="new channel")
    managed = SimpleNamespace(id=200, name="hangout")
    before = SimpleNamespace(channel=None)
    after = SimpleNamespace(channel=primary)

    class MutatingBus:
        def __init__(self):
            self.events = []

        async def emit(self, event_type, **data):
            self.events.append((event_type, data.copy()))
            if event_type == "discord_voice_state":
                # discord.py reuses and mutates the cached `after` VoiceState when
                # Auto Voice's move generates the next gateway event.
                data["after"].channel = managed

    bus = MutatingBus()
    bot = SimpleNamespace(modules=SimpleNamespace(event_bus=bus))
    member = SimpleNamespace(id=42)

    await BarkBot.on_voice_state_update(bot, member, before, after)

    raw_event = bus.events[0]
    persistence_event = bus.events[1]
    assert raw_event[1]["before_channel"] is None
    assert raw_event[1]["after_channel"] is primary
    assert persistence_event[1]["before_channel"] is None
    assert persistence_event[1]["after_channel"] is primary
    assert after.channel is managed


@pytest.mark.asyncio
async def test_server_event_buffer_records_and_bounds():
    from types import SimpleNamespace

    bot = BarkBot()
    member = SimpleNamespace(id=1, display_name="Alice", tag="Alice#0001")
    bot.record_server_event(1, "member_join", member, "Guild A")
    bot.record_server_event(1, "member_leave", SimpleNamespace(id=2, display_name="Bob", tag="Bob#0002"), "Guild A")

    events = bot.recent_server_events(1)
    assert len(events) == 2
    # Newest first.
    assert events[0]["type"] == "member_leave"
    assert events[0]["user_name"] == "Bob"
    assert events[1]["type"] == "member_join"
    assert events[1]["guild_name"] == "Guild A"
    assert events[1]["timestamp"]
    # No events for a different guild.
    assert bot.recent_server_events(2) == []


@pytest.mark.asyncio
async def test_server_event_buffer_is_bounded():
    from types import SimpleNamespace

    bot = BarkBot()
    for i in range(80):  # > maxlen (60)
        bot.record_server_event(7, "member_join", SimpleNamespace(id=i, display_name=f"u{i}", tag="x"), "G")
    events = bot.recent_server_events(7, limit=100)
    assert len(events) == 60  # deque maxlen bounds memory
    assert events[0]["user_name"] == "u79"
    assert events[-1]["user_name"] == "u20"


@pytest.mark.asyncio
async def test_message_stats_track_messages_channels_and_emojis():
    from types import SimpleNamespace

    bot = BarkBot()
    bot.record_message(5, SimpleNamespace(id=100, name="general"))
    bot.record_message(5, SimpleNamespace(id=100, name="general"))
    bot.record_message(5, SimpleNamespace(id=200, name="memes"))
    # Plain strings stand in for a custom emoji whose str() is its name.
    bot.record_reaction(5, "laugh")
    bot.record_reaction(5, "laugh")
    bot.record_reaction(5, "wow")

    stats = bot.message_stats(5)
    assert stats["messages"] == 3
    assert stats["channels"]["100"]["name"] == "general"
    assert stats["channels"]["100"]["count"] == 2
    assert stats["channels"]["200"]["count"] == 1
    assert stats["emojis"]["laugh"] == 2
    assert stats["emojis"]["wow"] == 1
    # A different guild is tracked independently.
    assert bot.message_stats(9)["messages"] == 0
    # All-time emoji accumulation persists alongside the daily window.
    assert bot.message_stats(5)["emoji_total"]["laugh"] == 2


@pytest.mark.asyncio
async def test_top_channels_aggregate_trailing_windows_and_all_time_emoji():
    from types import SimpleNamespace

    bot = BarkBot()
    # Today: general x2, memes x1
    bot.record_message(7, SimpleNamespace(id=100, name="general"))
    bot.record_message(7, SimpleNamespace(id=100, name="general"))
    bot.record_message(7, SimpleNamespace(id=200, name="memes"))
    # Seed a completed prior day into the daily history window.
    bot._message_stats[7]["history"].append(
        {"date": "2026-08-13", "channels": {"100": {"name": "general", "count": 5}}}
    )

    # 1-day window ignores history (today only).
    assert bot.top_channels(7, 1)[0] == {"name": "general", "count": 2}
    # 7-day window rolls history + today.
    top = bot.top_channels(7, 7)
    assert top[0] == {"name": "general", "count": 7}
    assert {c["name"] for c in top} == {"general", "memes"}

    # All-time emoji accumulates across daily resets.
    bot.record_reaction(7, "laugh")
    bot.record_reaction(7, "wow")
    # Force a date rollover; emoji_total must survive.
    bot._message_stats[7]["date"] = "2099-01-01"
    bot.record_reaction(7, "laugh")
    assert bot.message_stats(7)["emoji_total"]["laugh"] == 2
    assert bot.message_stats(7)["emoji_total"]["wow"] == 1


@pytest.mark.asyncio
async def test_on_interaction_logs_without_dispatching():
    """The framework (ConnectionState.parse_interaction_create) dispatches
    commands to the tree — on_interaction must only log. Calling a
    nonexistent tree.interaction() used to raise AttributeError and then
    send a bogus 'Something went wrong' response, failing the real command
    with error 40060 (already acknowledged)."""

    class RealisticTree:
        """Matches discord.py 2.7.1's CommandTree — no .interaction method."""

    sent = []

    class Response:
        def is_done(self):
            return False

        async def send_message(self, content, ephemeral=False):
            sent.append(content)

    bot = SimpleNamespace(
        tree=RealisticTree(),
        modules=SimpleNamespace(event_bus=SimpleNamespace(emit=lambda *a, **k: None)),
    )
    interaction = SimpleNamespace(
        data={"name": "bark", "id": "123"},
        type="application_command",
        guild_id=1,
        user=SimpleNamespace(id=42),
        response=Response(),
    )

    # Must not raise and must not respond — the tree owns dispatch.
    await BarkBot.on_interaction(bot, interaction)
    assert sent == []


@pytest.mark.asyncio
async def test_on_interaction_never_sends_error_message_for_framework_dispatch():
    """Even when the tree has no interaction method, on_interaction must not
    acknowledge the interaction with a fallback message (40060 double-ack)."""

    class NoDispatchTree:
        def __getattr__(self, name):
            raise AttributeError(f"{name} does not exist")

    sent = []

    class Response:
        def is_done(self):
            return False

        async def send_message(self, content, ephemeral=False):
            sent.append(content)

    bot = SimpleNamespace(
        tree=NoDispatchTree(),
        modules=SimpleNamespace(event_bus=SimpleNamespace(emit=lambda *a, **k: None)),
    )
    interaction = SimpleNamespace(
        data={"name": "bark", "id": "123"},
        type="application_command",
        guild_id=1,
        user=SimpleNamespace(id=42),
        response=Response(),
    )

    await BarkBot.on_interaction(bot, interaction)
    assert sent == []
