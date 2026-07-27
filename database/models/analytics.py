"""Analytics models — guild activity snapshots for dashboard stats."""

from datetime import date, datetime, timezone

from sqlalchemy import String, Integer, Date, DateTime, ForeignKey
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return (
            f"<ActivitySnapshot guild={self.guild_id} "
            f"date={self.snapshot_date} members={self.total_members}>"
        )
