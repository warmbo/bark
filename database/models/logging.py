"""
Logging configuration model.
"""

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.engine import Base


class LogConfig(Base):
    __tablename__ = "log_configs"
    __table_args__ = (UniqueConstraint("guild_id", "event_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("guilds.discord_id"), nullable=False
    , index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    guild = relationship("Guild", back_populates="log_configs")

    def __repr__(self) -> str:
        return f"<LogConfig guild_id={self.guild_id} event='{self.event_type}'>"
