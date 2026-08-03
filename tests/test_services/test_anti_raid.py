"""Anti-raid in-memory state bounding regressions."""

import pytest

from services.anti_raid import AntiRaidService


@pytest.mark.asyncio
async def test_violation_tracking_evicts_oldest_users_when_bounded(monkeypatch):
    monkeypatch.setattr(AntiRaidService, "MAX_TRACKED_USERS_PER_GUILD", 3)
    service = AntiRaidService()

    for user_id in range(1, 5):
        await service.record_violation(1, user_id)

    assert set(service._violation_count[1]) == {2, 3, 4}
    assert set(service._escalation_cooldown[1]) == {2, 3, 4}
    assert set(service._violation_seen[1]) == {2, 3, 4}


@pytest.mark.asyncio
async def test_violation_tracking_prunes_users_past_state_ttl():
    service = AntiRaidService()
    guild_id = 9
    await service.record_violation(guild_id, 1)
    service._violation_seen[guild_id][1] -= service.VIOLATION_STATE_TTL_SECONDS + 1

    await service.record_violation(guild_id, 2)

    assert 1 not in service._violation_seen[guild_id]
    assert 1 not in service._violation_count[guild_id]
    assert 1 not in service._escalation_cooldown[guild_id]
