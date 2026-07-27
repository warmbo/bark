import pytest

from services.event_bus import EventBus


class Listener:
    def __init__(self) -> None:
        self.calls = 0

    async def handle(self, event_type: str, **data) -> None:
        self.calls += 1


def test_unsubscribe_matches_fresh_bound_method_lookup():
    bus = EventBus()
    listener = Listener()
    bus.subscribe("event", listener.handle)

    assert bus.unsubscribe("event", listener.handle)
    assert bus.subscriber_count("event") == 0


@pytest.mark.asyncio
async def test_duplicate_bound_method_subscription_delivers_once():
    bus = EventBus()
    listener = Listener()
    bus.subscribe("event", listener.handle)
    bus.subscribe("event", listener.handle)

    await bus.emit("event")

    assert bus.subscriber_count("event") == 1
    assert listener.calls == 1
