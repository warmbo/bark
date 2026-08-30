"""Persisted one-time and recurring announcement jobs."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.engine import Base


class AnnouncementSchedule(Base):
    """A durable announcement waiting to be sent by the module worker."""

    __tablename__ = "announcement_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("guilds.discord_id"), nullable=False, index=True
    )
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    as_embed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    embed_color: Mapped[str] = mapped_column(String(16), nullable=False, default="#5865F2")
    image_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    video_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    timezone_name: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    recurrence_unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    recurrence_interval: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    recurrence_anchor_day: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
