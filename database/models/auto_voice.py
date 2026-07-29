"""Persistent state for Bark-managed temporary voice channels."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from database.engine import Base


class AutoVoiceChannel(Base):
    __tablename__ = "auto_voice_channels"

    channel_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    guild_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("guilds.discord_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id: Mapped[str] = mapped_column(String(32), nullable=False)
    primary_channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
