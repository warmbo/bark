"""Secure, one-time invitations for access to a hosted Bark instance."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.permissions import InstanceAccess, InstanceInvite

_TOKEN_BYTES = 32


def _affected_rows(result: object) -> int:
    """Return a typed SQLAlchemy DML row count."""
    return int(getattr(result, "rowcount", 0) or 0)


def token_digest(token: str) -> str:
    """Return the only representation of an invite token stored in the database."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def create_instance_invite(
    session: AsyncSession,
    *,
    created_by_discord_id: str,
    expires_at: datetime,
) -> tuple[InstanceInvite, str]:
    """Create a one-time invite and return its plaintext token exactly once."""
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    invite = InstanceInvite(
        token_hash=token_digest(token),
        created_by_discord_id=str(created_by_discord_id),
        expires_at=expires_at,
    )
    session.add(invite)
    await session.flush()
    return invite, token


async def redeem_instance_invite(
    session: AsyncSession,
    *,
    token: str,
    discord_user_id: str,
) -> InstanceAccess | None:
    """Atomically consume a valid invite and grant the signed-in user access."""
    now = _utc_now()
    # Consume with one guarded mutation.  A select-then-update would let two
    # concurrent OAuth callbacks both observe the same unused token.
    consumed = await session.execute(
        update(InstanceInvite)
        .where(
            InstanceInvite.token_hash == token_digest(token),
            InstanceInvite.redeemed_at.is_(None),
            InstanceInvite.revoked_at.is_(None),
            InstanceInvite.expires_at > now,
        )
        .values(redeemed_at=now, redeemed_by_discord_id=str(discord_user_id))
    )
    if _affected_rows(consumed) != 1:
        return None

    existing = (
        await session.execute(
            select(InstanceAccess).where(InstanceAccess.discord_user_id == str(discord_user_id))
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = InstanceAccess(discord_user_id=str(discord_user_id), role="admin")
        session.add(existing)
    elif existing.revoked_at is not None:
        existing.revoked_at = None
        existing.role = "admin"

    await session.flush()
    return existing


async def is_instance_user_authorized(session: AsyncSession, discord_user_id: str) -> bool:
    """Return whether a non-owner has an active hosted-instance grant."""
    access = (
        await session.execute(
            select(InstanceAccess).where(InstanceAccess.discord_user_id == str(discord_user_id))
        )
    ).scalar_one_or_none()
    return access is not None and access.revoked_at is None


async def authorize_instance_user(
    session: AsyncSession,
    *,
    discord_user_id: str,
    invite_token: str | None = None,
) -> bool:
    """Allow an existing grant, or consume the single pending invite token."""
    if await is_instance_user_authorized(session, discord_user_id):
        return True
    if not invite_token:
        return False
    return (
        await redeem_instance_invite(session, token=invite_token, discord_user_id=discord_user_id)
        is not None
    )


async def revoke_instance_invite(session: AsyncSession, invite_id: int) -> bool:
    """Revoke an unredeemed invitation without exposing its token."""
    invite = await session.get(InstanceInvite, invite_id)
    if invite is None or invite.redeemed_at is not None or invite.revoked_at is not None:
        return False
    invite.revoked_at = _utc_now()
    await session.flush()
    return True


async def list_instance_invites(session: AsyncSession) -> list[InstanceInvite]:
    result = await session.execute(
        select(InstanceInvite).order_by(InstanceInvite.created_at.desc())
    )
    return list(result.scalars().all())


async def list_instance_access(session: AsyncSession) -> list[InstanceAccess]:
    """Return every hosted-instance access grant, including revoked records."""
    result = await session.execute(
        select(InstanceAccess).order_by(InstanceAccess.granted_at.desc())
    )
    return list(result.scalars().all())


async def revoke_instance_access(session: AsyncSession, discord_user_id: str) -> bool:
    access = (
        await session.execute(
            select(InstanceAccess).where(InstanceAccess.discord_user_id == str(discord_user_id))
        )
    ).scalar_one_or_none()
    if access is None or access.revoked_at is not None:
        return False
    access.revoked_at = _utc_now()
    await session.flush()
    return True
