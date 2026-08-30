"""Persistence and state transitions for scheduled announcements."""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, update

from database.engine import session_scope
from database.models.announcements import AnnouncementSchedule


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_times(schedule: AnnouncementSchedule) -> AnnouncementSchedule:
    schedule.next_run_at = _as_utc(schedule.next_run_at)
    schedule.created_at = _as_utc(schedule.created_at)
    schedule.updated_at = _as_utc(schedule.updated_at)
    if schedule.last_run_at is not None:
        schedule.last_run_at = _as_utc(schedule.last_run_at)
    return schedule


def advance_recurrence(
    previous: datetime,
    *,
    unit: str,
    interval: int,
    timezone_name: str,
    after: datetime,
    anchor_day: int,
) -> datetime:
    """Return the first recurrence strictly after ``after`` in UTC.

    Day/week/month recurrences preserve the user's wall-clock time through DST.
    Month schedules retain their original day and clamp only in short months.
    Hour recurrences represent elapsed time and therefore advance in UTC.
    """
    if interval < 1 or unit not in {"hour", "day", "week", "month"}:
        raise ValueError("Unsupported recurrence")
    zone = ZoneInfo(timezone_name)
    candidate = _as_utc(previous)
    after = _as_utc(after)
    if unit == "hour":
        step = timedelta(hours=interval)
        if candidate > after:
            return candidate
        missed_steps = (after - candidate) // step + 1
        return candidate + step * missed_steps
    for _ in range(10000):
        local = candidate.astimezone(zone)
        if unit == "day":
            next_local = local + timedelta(days=interval)
        elif unit == "week":
            next_local = local + timedelta(weeks=interval)
        else:
            month_index = local.year * 12 + (local.month - 1) + interval
            year, zero_based_month = divmod(month_index, 12)
            month = zero_based_month + 1
            day = min(anchor_day, calendar.monthrange(year, month)[1])
            next_local = local.replace(year=year, month=month, day=day)
        candidate = next_local.astimezone(timezone.utc)
        if candidate > after:
            return candidate
    raise ValueError("Recurrence is too far behind to advance safely")


async def create_schedule(
    *,
    guild_id: str,
    channel_id: str,
    title: str,
    message: str,
    as_embed: bool,
    embed_color: str,
    image_url: str,
    video_url: str,
    scheduled_for: datetime,
    timezone_name: str,
    recurrence_unit: str | None,
    recurrence_interval: int,
    created_by: str,
) -> AnnouncementSchedule:
    """Create a queued announcement and return its persisted record."""
    schedule = AnnouncementSchedule(
        guild_id=str(guild_id),
        channel_id=str(channel_id),
        title=title,
        message=message,
        as_embed=as_embed,
        embed_color=embed_color,
        image_url=image_url,
        video_url=video_url,
        next_run_at=_as_utc(scheduled_for),
        timezone_name=timezone_name,
        recurrence_unit=recurrence_unit,
        recurrence_interval=recurrence_interval,
        recurrence_anchor_day=_as_utc(scheduled_for).astimezone(ZoneInfo(timezone_name)).day,
        created_by=str(created_by),
        status="queued",
    )
    async with session_scope() as session:
        session.add(schedule)
        await session.flush()
        await session.refresh(schedule)
    return _normalize_times(schedule)


async def list_schedules(guild_id: str) -> list[AnnouncementSchedule]:
    """List a guild's schedules, soonest first."""
    async with session_scope() as session:
        result = await session.execute(
            select(AnnouncementSchedule)
            .where(AnnouncementSchedule.guild_id == str(guild_id))
            .order_by(AnnouncementSchedule.next_run_at, AnnouncementSchedule.id)
        )
        schedules = list(result.scalars().all())
    return [_normalize_times(schedule) for schedule in schedules]


async def claim_next_due(
    now: datetime, eligible_guild_ids: set[str] | None = None
) -> AnnouncementSchedule | None:
    """Atomically move the next due queued job to ``sending``.

    The guarded UPDATE is the ownership boundary: competing workers may select
    the same candidate, but only one can change it from queued to sending.
    """
    now = _as_utc(now)
    async with session_scope() as session:
        conditions = [
            AnnouncementSchedule.status == "queued",
            AnnouncementSchedule.next_run_at <= now,
        ]
        if eligible_guild_ids is not None:
            if not eligible_guild_ids:
                return None
            conditions.append(AnnouncementSchedule.guild_id.in_(eligible_guild_ids))
        candidate_id = await session.scalar(
            select(AnnouncementSchedule.id)
            .where(*conditions)
            .order_by(AnnouncementSchedule.next_run_at, AnnouncementSchedule.id)
            .limit(1)
        )
        if candidate_id is None:
            return None
        result = await session.execute(
            update(AnnouncementSchedule)
            .where(
                AnnouncementSchedule.id == candidate_id,
                AnnouncementSchedule.status == "queued",
                AnnouncementSchedule.next_run_at <= now,
            )
            .values(status="sending", updated_at=now)
        )
        if getattr(result, "rowcount", 0) != 1:
            return None
        schedule = await session.get(AnnouncementSchedule, candidate_id)
    return _normalize_times(schedule) if schedule is not None else None


async def complete_delivery(schedule_id: int, *, sent_at: datetime) -> bool:
    """Record a successful send and complete or advance the claimed job."""
    sent_at = _as_utc(sent_at)
    async with session_scope() as session:
        schedule = await session.get(AnnouncementSchedule, schedule_id)
        if schedule is None or schedule.status != "sending":
            return False
        schedule.last_run_at = sent_at
        schedule.last_error = ""
        schedule.updated_at = sent_at
        if schedule.recurrence_unit is None:
            schedule.status = "completed"
        else:
            schedule.next_run_at = advance_recurrence(
                schedule.next_run_at,
                unit=schedule.recurrence_unit,
                interval=schedule.recurrence_interval,
                timezone_name=schedule.timezone_name,
                after=sent_at,
                anchor_day=schedule.recurrence_anchor_day,
            )
            schedule.status = "queued"
    return True


async def fail_delivery(schedule_id: int, *, failed_at: datetime, error: str) -> bool:
    """Stop a claimed job after an uncertain/failed send to prevent duplicates."""
    failed_at = _as_utc(failed_at)
    async with session_scope() as session:
        schedule = await session.get(AnnouncementSchedule, schedule_id)
        if schedule is None or schedule.status != "sending":
            return False
        schedule.status = "failed"
        schedule.last_run_at = failed_at
        schedule.last_error = str(error)[:1000]
        schedule.updated_at = failed_at
    return True


async def set_schedule_paused(guild_id: str, schedule_id: int, *, paused: bool) -> bool:
    """Pause or resume a guild-owned job unless it is actively sending."""
    target = "paused" if paused else "queued"
    allowed = {"queued", "failed"} if paused else {"paused", "failed"}
    now = datetime.now(timezone.utc)
    values = {"status": target, "updated_at": now}
    if not paused:
        values["last_error"] = ""
    async with session_scope() as session:
        result = await session.execute(
            update(AnnouncementSchedule)
            .where(
                AnnouncementSchedule.id == schedule_id,
                AnnouncementSchedule.guild_id == str(guild_id),
                AnnouncementSchedule.status.in_(allowed),
            )
            .values(**values)
        )
        return getattr(result, "rowcount", 0) == 1


async def delete_schedule(guild_id: str, schedule_id: int) -> bool:
    """Delete a guild-owned job unless a worker currently owns it."""
    async with session_scope() as session:
        result = await session.execute(
            delete(AnnouncementSchedule).where(
                AnnouncementSchedule.id == schedule_id,
                AnnouncementSchedule.guild_id == str(guild_id),
                AnnouncementSchedule.status != "sending",
            )
        )
        return getattr(result, "rowcount", 0) == 1


async def recover_interrupted_deliveries() -> int:
    """Surface jobs left in ``sending`` by a process restart without replaying them."""
    now = datetime.now(timezone.utc)
    async with session_scope() as session:
        result = await session.execute(
            update(AnnouncementSchedule)
            .where(AnnouncementSchedule.status == "sending")
            .values(
                status="failed",
                last_error="Bark restarted while this announcement was sending; review and retry it manually.",
                updated_at=now,
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)
