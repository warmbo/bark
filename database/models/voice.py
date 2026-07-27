"""
Voice session tracking model.

Records every voice channel join/leave with precise timestamps
so moderators can see who was in what channel and for how long.
"""

from datetime import datetime, timezone

from sqlalchemy import String, Integer, BigInteger, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.engine import Base


class VoiceSession(Base):
    __tablename__ = "voice_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(String(32), ForeignKey("guilds.discord_id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    user_tag: Mapped[str] = mapped_column(String(64), nullable=False, default="Unknown#0000")
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    channel_name: Mapped[str] = mapped_column(String(128), nullable=False, default="Unknown")
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    left_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    guild = relationship("Guild")

    def __repr__(self) -> str:
        return f"<VoiceSession user={self.user_id} channel={self.channel_name} joined={self.joined_at}>"
