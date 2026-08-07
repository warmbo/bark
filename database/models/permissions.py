"""
Dashboard user and permission models.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.engine import Base


class DashboardUser(Base):
    __tablename__ = "dashboard_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discord_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    avatar_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="viewer"
    )  # owner/admin/moderator/viewer
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<DashboardUser discord_id={self.discord_id} role='{self.role}'>"


class InstanceInvite(Base):
    """A one-time, owner-issued invitation to a hosted Bark instance."""

    __tablename__ = "instance_invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_by_discord_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    redeemed_by_discord_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class InstanceAccess(Base):
    """An active grant that permits a Discord user to use this Bark instance."""

    __tablename__ = "instance_access"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discord_user_id: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="admin")
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DashboardGuildAccess(Base):
    """Latest Discord OAuth guild snapshot for a dashboard user."""

    __tablename__ = "dashboard_guild_access"
    __table_args__ = (
        UniqueConstraint("user_discord_id", "guild_id", name="uq_dashboard_user_guild"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_discord_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("dashboard_users.discord_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    guild_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    icon_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    permissions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    owner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_manage: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Comma-separated Discord role IDs the user held in this guild at login.
    # Used to resolve owner-configured moderator roles per server ("Ready to
    # manage" gating). Empty when the bot was not in the guild or the member
    # was not resolvable from the bot cache.
    roles: Mapped[str] = mapped_column(String(512), nullable=False, default="")


class ModuleRoleAccess(Base):
    """Per-guild minimum dashboard role for a module."""

    __tablename__ = "module_role_access"
    __table_args__ = (UniqueConstraint("guild_id", "module_name", name="uq_module_role_guild"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("guilds.discord_id"), nullable=False, index=True
    )
    module_name: Mapped[str] = mapped_column(String(64), nullable=False)
    min_role: Mapped[str] = mapped_column(String(16), nullable=False, default="admin")
