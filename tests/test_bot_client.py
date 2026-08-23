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
