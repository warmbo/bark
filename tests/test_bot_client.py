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
