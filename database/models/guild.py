"""
Guild configuration models.
"""

from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.engine import Base


class Guild(Base):
    __tablename__ = "guilds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discord_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="Unknown")
    owner_id: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    prefix: Mapped[str] = mapped_column(String(16), nullable=False, default="!")
    locale: Mapped[str] = mapped_column(String(8), nullable=False, default="en-US")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships (parent side — specify primaryjoin since children lack FK constraints
    # across the relationship graph during mapper config)
    settings = relationship("GuildSetting", back_populates="guild", cascade="all, delete-orphan",
                            primaryjoin="GuildSetting.guild_id == Guild.id")
    module_configs = relationship("ModuleConfig", back_populates="guild", cascade="all, delete-orphan",
                                  primaryjoin="ModuleConfig.guild_id == Guild.id")
    moderation_cases = relationship("ModerationCase", back_populates="guild", cascade="all, delete-orphan",
                                    primaryjoin="ModerationCase.guild_id == Guild.id")
    log_configs = relationship("LogConfig", back_populates="guild", cascade="all, delete-orphan",
                               primaryjoin="LogConfig.guild_id == Guild.id")
    automod_configs = relationship("AutoModConfig", back_populates="guild", cascade="all, delete-orphan",
                                   primaryjoin="AutoModConfig.guild_id == Guild.id")
    warnings = relationship("Warning", back_populates="guild", cascade="all, delete-orphan",
                            primaryjoin="Warning.guild_id == Guild.id")
    user_notes = relationship("UserNote", back_populates="guild", cascade="all, delete-orphan",
                              primaryjoin="UserNote.guild_id == Guild.id")
    audit_logs = relationship("AuditLog", back_populates="guild", cascade="all, delete-orphan",
                              primaryjoin="AuditLog.guild_id == Guild.id")

    def __repr__(self) -> str:
        return f"<Guild id={self.discord_id} name='{self.name}'>"


class GuildSetting(Base):
    __tablename__ = "guild_settings"
    __table_args__ = (UniqueConstraint("guild_id", "key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(Integer, ForeignKey("guilds.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")

    guild = relationship("Guild", back_populates="settings")

    def __repr__(self) -> str:
        return f"<GuildSetting guild_id={self.guild_id} key='{self.key}'>"
