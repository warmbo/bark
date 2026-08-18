"""Analytics models — guild activity snapshots for dashboard stats.

The Statistics page reads entirely from the database (not in-memory bot
counters). Per-day message/emoji aggregates are written on every event so the
DB builds knowledge about the server over time and always has data, even right
after a bot restart.
"""

from datetime import date, datetime, timezone

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.engine import Base


class ActivitySnapshot(Base):
    """Daily snapshot of guild activity metrics."""

    __tablename__ = "activity_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("guilds.discord_id"), nullable=False, index=True
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_messages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_voice_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_reactions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_members: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_members: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    left_members: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_members: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mod_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    automod_triggers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message_authors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    channels_active: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_channels: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    threads_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Per-channel message counts for the snapshot day, stored as a JSON object
    # mapping channel_id -> {"name": str, "count": int}. Maintained as a rolling
    # view of the DailyChannelStat table for a given day.
    channel_messages: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # Per-emoji reaction counts (and all-time totals) for the snapshot day,
    # stored as a JSON object mapping emoji name -> count.
    emoji_counts: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return (
            f"<ActivitySnapshot guild={self.guild_id} "
            f"date={self.snapshot_date} members={self.total_members}>"
        )


class DailyChannelStat(Base):
    """Per-guild, per-day message count per text channel.

    One row per (guild, day, channel), upserted on every non-bot message so the
    database is the source of truth for channel activity. The Statistics page
    aggregates these rows for today / 7d / 30d windows.
    """

    __tablename__ = "daily_channel_stats"
    __table_args__ = (
        UniqueConstraint("guild_id", "stat_date", "channel_id", name="uq_daily_channel_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("guilds.discord_id"), nullable=False, index=True
    )
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    channel_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return (
            f"<DailyChannelStat guild={self.guild_id} {self.stat_date} "
            f"#{self.channel_name} {self.message_count}>"
        )


class DailyEmojiStat(Base):
    """Per-guild, per-day reaction count per emoji.

    One row per (guild, day, emoji), upserted on every reaction so all-time
    emoji totals accumulate in the database.
    """

    __tablename__ = "daily_emoji_stats"
    __table_args__ = (
        UniqueConstraint("guild_id", "stat_date", "emoji_name", name="uq_daily_emoji_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("guilds.discord_id"), nullable=False, index=True
    )
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    emoji_name: Mapped[str] = mapped_column(String(120), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return (
            f"<DailyEmojiStat guild={self.guild_id} {self.stat_date} "
            f"{self.emoji_name} {self.count}>"
        )

