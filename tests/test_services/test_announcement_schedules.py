"""Durable announcement scheduling service tests."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.asyncio
async def test_create_schedule_persists_complete_announcement_payload(db):
    from database.engine import session_scope
    from database.models.guild import Guild
    from services.announcement_schedules import create_schedule, list_schedules

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test Guild"))

    scheduled_for = datetime(2026, 9, 1, 15, 30, tzinfo=timezone.utc)
    created = await create_schedule(
        guild_id="1",
        channel_id="55",
        title="Maintenance",
        message="Servers restart soon.",
        as_embed=True,
        embed_color="#5865F2",
        image_url="https://example.com/image.png",
        video_url="https://example.com/video",
        scheduled_for=scheduled_for,
        timezone_name="America/Chicago",
        recurrence_unit=None,
        recurrence_interval=1,
        created_by="42",
    )

    schedules = await list_schedules("1")

    assert created.id is not None
    assert len(schedules) == 1
    schedule = schedules[0]
    assert schedule.guild_id == "1"
    assert schedule.channel_id == "55"
    assert schedule.title == "Maintenance"
    assert schedule.message == "Servers restart soon."
    assert schedule.as_embed is True
    assert schedule.embed_color == "#5865F2"
    assert schedule.image_url == "https://example.com/image.png"
    assert schedule.video_url == "https://example.com/video"
    assert schedule.next_run_at == scheduled_for
    assert schedule.timezone_name == "America/Chicago"
    assert schedule.recurrence_unit is None
    assert schedule.status == "queued"
    assert schedule.created_by == "42"


@pytest.mark.asyncio
async def test_concurrent_workers_claim_due_schedule_only_once(db):
    from database.engine import session_scope
    from database.models.guild import Guild
    from services.announcement_schedules import claim_next_due, create_schedule

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test Guild"))

    now = datetime.now(timezone.utc)
    await create_schedule(
        guild_id="1",
        channel_id="55",
        title="",
        message="Due now",
        as_embed=False,
        embed_color="#5865F2",
        image_url="",
        video_url="",
        scheduled_for=now - timedelta(seconds=1),
        timezone_name="UTC",
        recurrence_unit=None,
        recurrence_interval=1,
        created_by="42",
    )

    claims = await asyncio.gather(claim_next_due(now), claim_next_due(now))

    claimed = [schedule for schedule in claims if schedule is not None]
    assert len(claimed) == 1
    assert claimed[0].status == "sending"
    assert claimed[0].message == "Due now"


def test_daily_recurrence_preserves_local_time_across_dst():
    from services.announcement_schedules import advance_recurrence

    previous = datetime(2026, 3, 7, 15, 0, tzinfo=timezone.utc)  # 09:00 CST

    next_run = advance_recurrence(
        previous,
        unit="day",
        interval=1,
        timezone_name="America/Chicago",
        after=previous,
        anchor_day=7,
    )

    assert next_run == datetime(2026, 3, 8, 14, 0, tzinfo=timezone.utc)  # 09:00 CDT


def test_monthly_recurrence_returns_to_anchor_day_after_short_month():
    from services.announcement_schedules import advance_recurrence

    january = datetime(2026, 1, 31, 15, 0, tzinfo=timezone.utc)
    february = advance_recurrence(
        january,
        unit="month",
        interval=1,
        timezone_name="UTC",
        after=january,
        anchor_day=31,
    )
    march = advance_recurrence(
        february,
        unit="month",
        interval=1,
        timezone_name="UTC",
        after=february,
        anchor_day=31,
    )

    assert february == datetime(2026, 2, 28, 15, 0, tzinfo=timezone.utc)
    assert march == datetime(2026, 3, 31, 15, 0, tzinfo=timezone.utc)


def test_hourly_recurrence_skips_long_outage_without_replaying_missed_runs():
    from services.announcement_schedules import advance_recurrence

    previous = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    after = datetime(2026, 8, 30, 3, 0, tzinfo=timezone.utc)

    next_run = advance_recurrence(
        previous,
        unit="hour",
        interval=1,
        timezone_name="UTC",
        after=after,
        anchor_day=1,
    )

    assert next_run == datetime(2026, 8, 30, 4, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_successful_recurring_schedule_returns_to_queue_at_next_run(db):
    from database.engine import session_scope
    from database.models.guild import Guild
    from services.announcement_schedules import (
        claim_next_due,
        complete_delivery,
        create_schedule,
        list_schedules,
    )

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test Guild"))

    first_run = datetime(2026, 1, 31, 15, 0, tzinfo=timezone.utc)
    await create_schedule(
        guild_id="1",
        channel_id="55",
        title="Monthly",
        message="Monthly news",
        as_embed=True,
        embed_color="#5865F2",
        image_url="",
        video_url="",
        scheduled_for=first_run,
        timezone_name="UTC",
        recurrence_unit="month",
        recurrence_interval=1,
        created_by="42",
    )
    claimed = await claim_next_due(first_run)
    assert claimed is not None

    await complete_delivery(claimed.id, sent_at=first_run)

    schedule = (await list_schedules("1"))[0]
    assert schedule.status == "queued"
    assert schedule.last_run_at == first_run
    assert schedule.next_run_at == datetime(2026, 2, 28, 15, 0, tzinfo=timezone.utc)
    assert schedule.last_error == ""


@pytest.mark.asyncio
async def test_failed_delivery_stops_job_without_automatic_duplicate(db):
    from database.engine import session_scope
    from database.models.guild import Guild
    from services.announcement_schedules import (
        claim_next_due,
        create_schedule,
        fail_delivery,
        list_schedules,
    )

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test Guild"))

    due = datetime.now(timezone.utc)
    await create_schedule(
        guild_id="1",
        channel_id="55",
        title="",
        message="Do not duplicate",
        as_embed=False,
        embed_color="#5865F2",
        image_url="",
        video_url="",
        scheduled_for=due,
        timezone_name="UTC",
        recurrence_unit=None,
        recurrence_interval=1,
        created_by="42",
    )
    claimed = await claim_next_due(due)
    assert claimed is not None

    await fail_delivery(claimed.id, failed_at=due, error="Missing channel")

    schedule = (await list_schedules("1"))[0]
    assert schedule.status == "failed"
    assert schedule.last_run_at == due
    assert schedule.last_error == "Missing channel"
    assert await claim_next_due(due + timedelta(days=1)) is None


@pytest.mark.asyncio
async def test_pause_resume_and_delete_are_guild_scoped(db):
    from database.engine import session_scope
    from database.models.guild import Guild
    from services.announcement_schedules import (
        create_schedule,
        delete_schedule,
        list_schedules,
        set_schedule_paused,
    )

    async with session_scope() as session:
        session.add_all(
            [Guild(discord_id="1", name="One"), Guild(discord_id="2", name="Two")]
        )
    created = await create_schedule(
        guild_id="1",
        channel_id="55",
        title="",
        message="Control me",
        as_embed=False,
        embed_color="#5865F2",
        image_url="",
        video_url="",
        scheduled_for=datetime.now(timezone.utc) + timedelta(hours=1),
        timezone_name="UTC",
        recurrence_unit=None,
        recurrence_interval=1,
        created_by="42",
    )

    assert await set_schedule_paused("2", created.id, paused=True) is False
    assert await delete_schedule("2", created.id) is False
    assert await set_schedule_paused("1", created.id, paused=True) is True
    assert (await list_schedules("1"))[0].status == "paused"
    assert await set_schedule_paused("1", created.id, paused=False) is True
    assert (await list_schedules("1"))[0].status == "queued"
    assert await delete_schedule("1", created.id) is True
    assert await list_schedules("1") == []


@pytest.mark.asyncio
async def test_restart_marks_interrupted_sends_failed_instead_of_retrying(db):
    from database.engine import session_scope
    from database.models.guild import Guild
    from services.announcement_schedules import (
        claim_next_due,
        create_schedule,
        list_schedules,
        recover_interrupted_deliveries,
    )

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test Guild"))
    due = datetime.now(timezone.utc)
    await create_schedule(
        guild_id="1",
        channel_id="55",
        title="",
        message="Claimed before restart",
        as_embed=False,
        embed_color="#5865F2",
        image_url="",
        video_url="",
        scheduled_for=due,
        timezone_name="UTC",
        recurrence_unit=None,
        recurrence_interval=1,
        created_by="42",
    )
    assert await claim_next_due(due) is not None

    recovered = await recover_interrupted_deliveries()

    assert recovered == 1
    schedule = (await list_schedules("1"))[0]
    assert schedule.status == "failed"
    assert "restart" in schedule.last_error.lower()
    assert await claim_next_due(due + timedelta(days=1)) is None
