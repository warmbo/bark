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


def test_prune_idle_users_evicts_stale_content_and_mention_keys():
    """Content/mention deques are bounded but their (guild, user) keys were
    never evicted; prune_idle_users must drop idle users and empty guilds."""
    from datetime import datetime, timedelta, timezone

    service = AntiRaidService()
    old = datetime.now(timezone.utc) - timedelta(minutes=30)
    fresh = datetime.now(timezone.utc)

    service._recent_content[1][100].append(old)
    service._recent_content[1][101].append(fresh)
    service._mention_track[1][100].append((old, 3))
    service._mention_track[2][200].append(fresh)

    removed = service.prune_idle_users(1, idle_seconds=600)

    # Two stale entries removed (user 100 in both trackers); fresh stays.
    assert removed == 2
    assert 100 not in service._recent_content[1]
    assert 101 in service._recent_content[1]
    assert 100 not in service._mention_track[1]
    # Guild 2 untouched.
    assert service._mention_track[2][200]


def test_prune_trackers_removes_user_and_empty_guild():
    service = AntiRaidService()
    service._recent_content[1][100].append("hello")
    service._mention_track[1][100].append((1, 2))

    service.prune_trackers(1, 100)

    assert 1 not in service._recent_content
    assert 1 not in service._mention_track
