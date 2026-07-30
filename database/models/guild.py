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

    # Relationships (parent side)
    settings = relationship("GuildSetting", back_populates="guild", cascade="all, delete-orphan",
                            primaryjoin="GuildSetting.guild_id == Guild.discord_id")

    moderation_cases = relationship("ModerationCase", back_populates="guild", cascade="all, delete-orphan",
                                    primaryjoin="ModerationCase.guild_id == Guild.discord_id")
    log_configs = relationship("LogConfig", back_populates="guild", cascade="all, delete-orphan",
                               primaryjoin="LogConfig.guild_id == Guild.discord_id")
    automod_configs = relationship("AutoModConfig", back_populates="guild", cascade="all, delete-orphan",
                                   primaryjoin="AutoModConfig.guild_id == Guild.discord_id")
    warnings = relationship("Warning", back_populates="guild", cascade="all, delete-orphan",
                            primaryjoin="Warning.guild_id == Guild.discord_id")
    user_notes = relationship("UserNote", back_populates="guild", cascade="all, delete-orphan",
                              primaryjoin="UserNote.guild_id == Guild.discord_id")
    audit_logs = relationship("AuditLog", back_populates="guild", cascade="all, delete-orphan",
                              primaryjoin="AuditLog.guild_id == Guild.discord_id")
    rulesets = relationship("RuleSet", back_populates="guild", cascade="all, delete-orphan",
                            primaryjoin="RuleSet.guild_id == Guild.discord_id",
                            order_by="RuleSet.priority")
    word_lists = relationship("WordList", back_populates="guild", cascade="all, delete-orphan",
                              primaryjoin="WordList.guild_id == Guild.discord_id")
    reputation_profiles = relationship("ReputationProfile", back_populates="guild", cascade="all, delete-orphan",
                                       primaryjoin="ReputationProfile.guild_id == Guild.discord_id")
    reputation_events = relationship("ReputationEvent", back_populates="guild", cascade="all, delete-orphan",
                                     primaryjoin="ReputationEvent.guild_id == Guild.discord_id")
    reputation_tiers = relationship("ReputationTier", back_populates="guild", cascade="all, delete-orphan",
                                    primaryjoin="ReputationTier.guild_id == Guild.discord_id")
    reputation_rewards = relationship("ReputationReward", back_populates="guild", cascade="all, delete-orphan",
                                      primaryjoin="ReputationReward.guild_id == Guild.discord_id")

    def __repr__(self) -> str:
        return f"<Guild id={self.discord_id} name='{self.name}'>"


class GuildSetting(Base):
    __tablename__ = "guild_settings"
    __table_args__ = (UniqueConstraint("guild_id", "key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(String(32), ForeignKey("guilds.discord_id"), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")

    guild = relationship("Guild", back_populates="settings")

    def __repr__(self) -> str:
        return f"<GuildSetting guild_id={self.guild_id} key='{self.key}'>"
