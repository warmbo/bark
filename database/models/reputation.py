"""Reputation/ranking models — points, tiers, rewards, and credit events."""

from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.engine import Base


class ReputationProfile(Base):
    """Aggregate reputation state per guild member — score, level, tier."""

    __tablename__ = "reputation_profiles"
    __table_args__ = (UniqueConstraint("guild_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("guilds.discord_id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    total_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_tier: Mapped[str] = mapped_column(String(64), nullable=False, default="unranked")
    weekly_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    monthly_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    thanks_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    messages_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reactions_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    voice_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_activity: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    month_start: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    guild = relationship("Guild", back_populates="reputation_profiles")

    def __repr__(self) -> str:
        return f"<ReputationProfile guild={self.guild_id} user={self.user_id} lv{self.level} score={self.total_score:.0f}>"


class ReputationEvent(Base):
    """Individual credit event — one row per scored action."""

    __tablename__ = "reputation_events"
    __table_args__ = (
        UniqueConstraint(
            "guild_id", "event_type", "actor_id", "message_id", name="uq_reputation_event"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("guilds.discord_id"), nullable=False, index=True
    )
    actor_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    """message|reaction|emoji|thanks|voice_minute"""
    points: Mapped[float] = mapped_column(Float, nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )

    guild = relationship("Guild", back_populates="reputation_events")

    def __repr__(self) -> str:
        return f"<ReputationEvent guild={self.guild_id} type={self.event_type} +{self.points}>"


class ReputationTier(Base):
    """Named tier with symbol, score threshold, and optional Discord role."""

    __tablename__ = "reputation_tiers"
    __table_args__ = (UniqueConstraint("guild_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("guilds.discord_id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, default="★")
    min_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    min_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    color_hex: Mapped[str] = mapped_column(String(7), nullable=False, default="#99aab5")
    role_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    assign_role: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    guild = relationship("Guild", back_populates="reputation_tiers")

    def __repr__(self) -> str:
        return f"<ReputationTier guild={self.guild_id} '{self.symbol} {self.name}' score≥{self.min_score}>"


class ReputationReward(Base):
    """Configurable reward unlocked at a given tier or level."""

    __tablename__ = "reputation_rewards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("guilds.discord_id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reward_type: Mapped[str] = mapped_column(String(32), nullable=False)
    """role|access|badge|announcement"""
    reward_value: Mapped[str] = mapped_column(String(255), nullable=False)
    """role_id|channel_id|badge_name|announcement_template"""
    required_tier: Mapped[str] = mapped_column(String(64), nullable=False, default="unranked")
    required_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consume_on_award: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_award: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    guild = relationship("Guild", back_populates="reputation_rewards")

    def __repr__(self) -> str:
        return f"<ReputationReward guild={self.guild_id} '{self.name}' [{self.reward_type}]>"


class ReputationAward(Base):
    """Award record — tracks which rewards have been given to which members."""

    __tablename__ = "reputation_awards"
    __table_args__ = (UniqueConstraint("guild_id", "user_id", "reward_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("guilds.discord_id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reward_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reputation_rewards.id"), nullable=False
    )
    tier_name: Mapped[str] = mapped_column(String(64), nullable=False)
    level_at_award: Mapped[int] = mapped_column(Integer, nullable=False)
    score_at_award: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    reward = relationship("ReputationReward")

    def __repr__(self) -> str:
        return (
            f"<ReputationAward guild={self.guild_id} user={self.user_id} reward={self.reward_id}>"
        )
