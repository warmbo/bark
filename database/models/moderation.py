"""
Moderation models — cases, warnings, notes, audit logs.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.engine import Base


class ModerationCase(Base):
    __tablename__ = "moderation_cases"
    __table_args__ = (UniqueConstraint("guild_id", "case_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("guilds.discord_id"), nullable=False
    )
    case_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # warn/timeout/kick/ban/unban
    target_id: Mapped[str] = mapped_column(String(32), nullable=False)
    target_tag: Mapped[str] = mapped_column(String(64), nullable=False, default="Unknown#0000")
    moderator_id: Mapped[str] = mapped_column(String(32), nullable=False)
    moderator_tag: Mapped[str] = mapped_column(String(64), nullable=False, default="Unknown#0000")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)  # minutes (for timeout)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    guild = relationship("Guild", back_populates="moderation_cases")

    def __repr__(self) -> str:
        return f"<Case #{self.case_number} guild={self.guild_id} {self.action_type}>"


class Warning(Base):
    __tablename__ = "warnings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("guilds.discord_id"), nullable=False
    )
    case_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("moderation_cases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    moderator_id: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    guild = relationship("Guild", back_populates="warnings")

    def __repr__(self) -> str:
        return f"<Warning id={self.id} user={self.user_id}>"


class UserNote(Base):
    __tablename__ = "user_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("guilds.discord_id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    author_id: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    guild = relationship("Guild", back_populates="user_notes")

    def __repr__(self) -> str:
        return f"<UserNote id={self.id} user={self.user_id}>"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("guilds.discord_id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    guild = relationship("Guild", back_populates="audit_logs")

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} action='{self.action}'>"
