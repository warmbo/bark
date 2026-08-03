"""Role manager models — rules and assignment history."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.engine import Base


class RoleRule(Base):
    """A rule that auto-assigns a Discord role based on a trigger.

    rule_type: welcome | tenure | voice | stream | reaction
    trigger_config: JSON dict with rule-specific settings, e.g.
        - welcome: {}
        - tenure:  {"days_required": 30}
        - voice:   {"minutes_required": 0}
        - stream:  {"platform": "twitch"}
        - reaction: {"channel_id": "...", "emoji": "🎮"}
    """

    __tablename__ = "role_rules"
    __table_args__ = (UniqueConstraint("guild_id", "rule_type", "role_id", "trigger_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(String(32), ForeignKey("guilds.discord_id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    role_id: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    """Disambiguator — e.g. tenure days or reaction emoji. Empty for singleton types."""
    trigger_config: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    remove_when_inactive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """True for voice/stream/reaction: remove the role when the condition ends."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    guild = relationship("Guild", back_populates="role_rules")

    def __repr__(self) -> str:
        return f"<RoleRule guild={self.guild_id} '{self.name}' [{self.rule_type}] role={self.role_id}>"


class RoleAssignment(Base):
    """Audit log of role assignments/removals performed by the module."""

    __tablename__ = "role_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(String(32), ForeignKey("guilds.discord_id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    role_id: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("role_rules.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    """add | remove"""
    reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    rule = relationship("RoleRule")

    def __repr__(self) -> str:
        return f"<RoleAssignment guild={self.guild_id} user={self.user_id} {self.action} role={self.role_id}>"
