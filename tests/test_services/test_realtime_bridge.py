"""Regression tests for EventBus producers and the realtime SSE bridge."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.bark_context import BarkContext
from services.event_bus import EventBus
from services.realtime_bridge import EVENT_MAP, RealtimeBridge


async def _next_payload(queue: asyncio.Queue) -> str:
    return await asyncio.wait_for(queue.get(), timeout=1)


@pytest.mark.asyncio
async def test_event_bus_bridge_delivers_supported_events_to_only_the_target_guild():
    bus = EventBus()
    bridge = RealtimeBridge(bus)
    target = await bridge.subscribe("42")
    other = await bridge.subscribe("99")
    await bridge.start()

    payloads = {
        "moderation_case_created": dict(guild_id=42, case_id=7, action_type="warn"),
        "automod_triggered": dict(guild_id=42, rule="spam", action="delete"),
    }
    for event_name, payload in payloads.items():
        await bus.emit(event_name, **payload)
        message = await _next_payload(target)
        expected_sse_name = EVENT_MAP[event_name][0]
        assert message.startswith(f"event: {expected_sse_name}\n")
        assert '"guild_id": "42"' in message

    assert other.empty()
    assert "ticket_created" not in EVENT_MAP
    await bridge.stop()


@pytest.mark.asyncio
async def test_create_case_producer_reaches_realtime_bridge(monkeypatch):
    from services.moderation_service import ModerationService

    monkeypatch.setattr(ModerationService, "create_case", AsyncMock(return_value=12))

    bus = EventBus()
    bridge = RealtimeBridge(bus)
    queue = await bridge.subscribe("42")
    await bridge.start()
    ctx = BarkContext(MagicMock(), bus)

    case_number = await ctx.create_case(42, "warn", "10", "Target", "11", "Moderator", "Reason")
    message = await _next_payload(queue)

    assert case_number == 12
    assert message.startswith("event: new_moderation_case\n")
    assert '"case_id": 12' in message
    assert '"guild_id": "42"' in message
    await bridge.stop()


@pytest.mark.asyncio
async def test_automod_producer_emits_guild_scoped_event():
    from modules.moderation.module import ModerationModule

    bus = EventBus()
    bridge = RealtimeBridge(bus)
    queue = await bridge.subscribe("42")
    await bridge.start()

    module = ModerationModule.__new__(ModerationModule)
    module._logger = logging.getLogger("test.moderation")
    module.ctx = MagicMock()
    module.ctx.events = bus
    module.ctx.log_audit = AsyncMock()
    module.ctx.bot = SimpleNamespace(user=SimpleNamespace(id="1", name="bark"))
    module._anti_raid = MagicMock()
    module._anti_raid.record_violation = AsyncMock(return_value=(None, 1))
    message = MagicMock()
    message.guild.id = 42
    message.guild.name = "Test"
    message.guild.owner = None
    message.guild.owner_id = 1
    message.guild.get_member.return_value = None
    message.author.id = 8
    message.author.__str__.return_value = "Spammer"
    message.content = "duplicate content"
    message.delete = AsyncMock()

    await module._take_action(message, {"action": "delete"}, "Duplicate spam")
    delivered = await _next_payload(queue)

    assert delivered.startswith("event: automod_triggered\n")
    assert '"guild_id": "42"' in delivered
    assert '"action": "delete"' in delivered
    await bridge.stop()
