"""Tests for hosted-instance invitation security and lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from database.engine import session_scope
from database.models.permissions import DashboardUser, InstanceAccess, InstanceInvite
from services.instance_invites import (
    create_instance_invite,
    delete_instance_access,
    delete_instance_invite,
    is_instance_user_authorized,
    redeem_instance_invite,
    revoke_instance_access,
    revoke_instance_invite,
    token_digest,
)


@pytest.mark.asyncio
async def test_invite_token_is_stored_only_as_a_digest(db):
    async with session_scope() as session:
        invite, token = await create_instance_invite(
            session,
            created_by_discord_id="owner",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        await session.flush()

    assert token
    assert invite.token_hash == token_digest(token)
    assert invite.token_hash != token


@pytest.mark.asyncio
async def test_redeeming_an_active_invite_authorizes_the_invited_user(db):
    async with session_scope() as session:
        session.add(DashboardUser(discord_id="recipient", username="Recipient", role="viewer"))
        _, token = await create_instance_invite(
            session,
            created_by_discord_id="owner",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )

    async with session_scope() as session:
        access = await redeem_instance_invite(session, token=token, discord_user_id="recipient")

    assert access.discord_user_id == "recipient"
    assert access.role == "admin"


@pytest.mark.asyncio
async def test_invite_cannot_be_redeemed_after_expiry_or_by_a_second_user(db):
    async with session_scope() as session:
        _, expired = await create_instance_invite(
            session,
            created_by_discord_id="owner",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        _, active = await create_instance_invite(
            session,
            created_by_discord_id="owner",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )

    async with session_scope() as session:
        assert (
            await redeem_instance_invite(session, token=expired, discord_user_id="recipient")
            is None
        )
        first_access = await redeem_instance_invite(
            session, token=active, discord_user_id="recipient"
        )
        second_access = await redeem_instance_invite(session, token=active, discord_user_id="other")

    assert first_access is not None
    assert second_access is None


@pytest.mark.asyncio
async def test_revoked_access_is_not_authorized(db):
    async with session_scope() as session:
        _, token = await create_instance_invite(
            session,
            created_by_discord_id="owner",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        await redeem_instance_invite(session, token=token, discord_user_id="recipient")

    async with session_scope() as session:
        assert await revoke_instance_access(session, "recipient")

    async with session_scope() as session:
        assert not await is_instance_user_authorized(session, "recipient")


@pytest.mark.asyncio
async def test_delete_invite_removes_revoked_row_but_revoke_refuses(db):
    """The X action hard-deletes a dead (revoked) invite row, while the Revoke
    action still refuses to touch one that is already revoked."""
    async with session_scope() as session:
        invite, _ = await create_instance_invite(
            session,
            created_by_discord_id="owner",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        assert await revoke_instance_invite(session, invite.id)

    async with session_scope() as session:
        # Revoke (soft) must refuse an already-revoked invite...
        assert not await revoke_instance_invite(session, invite.id)
        # ...but remove (hard) succeeds.
        assert await delete_instance_invite(session, invite.id)

    async with session_scope() as session:
        row = await session.get(InstanceInvite, invite.id)
    assert row is None, "hard delete removed the invite row"


@pytest.mark.asyncio
async def test_delete_invite_removes_expired_row(db):
    """Expired invites are dead links; the remove action clears them."""
    async with session_scope() as session:
        invite, _ = await create_instance_invite(
            session,
            created_by_discord_id="owner",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )

    async with session_scope() as session:
        assert await delete_instance_invite(session, invite.id)

    async with session_scope() as session:
        assert await session.get(InstanceInvite, invite.id) is None


@pytest.mark.asyncio
async def test_delete_invite_removes_redeemed_row(db):
    """A redeemed (consumed) invite can be tidied off the list too."""
    async with session_scope() as session:
        session.add(DashboardUser(discord_id="recipient", username="Recipient", role="viewer"))
        invite, token = await create_instance_invite(
            session,
            created_by_discord_id="owner",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        await redeem_instance_invite(session, token=token, discord_user_id="recipient")

    async with session_scope() as session:
        # redeem_instance_invite runs a bulk UPDATE, so the stale in-memory
        # `invite` object is not refreshed — verify redemption from the DB.
        row = await session.get(InstanceInvite, invite.id)
        assert row is not None and row.redeemed_at is not None

    async with session_scope() as session:
        assert await delete_instance_invite(session, invite.id)

    async with session_scope() as session:
        assert await session.get(InstanceInvite, invite.id) is None


@pytest.mark.asyncio
async def test_delete_invite_missing_id_returns_false(db):
    async with session_scope() as session:
        assert await delete_instance_invite(session, 999999) is False


@pytest.mark.asyncio
async def test_delete_access_removes_revoked_grant_but_revoke_refuses(db):
    """A revoked access grant must be removable from the list (hard delete),
    while the soft Revoke action still refuses an already-revoked grant."""
    async with session_scope() as session:
        session.add(DashboardUser(discord_id="u1", username="User", role="viewer"))
        grant = InstanceAccess(discord_user_id="u1", role="admin")
        session.add(grant)
        await session.flush()
        assert await revoke_instance_access(session, "u1")

    async with session_scope() as session:
        # Revoke (soft) refuses an already-revoked grant...
        assert not await revoke_instance_access(session, "u1")
        # ...but remove (hard) succeeds and drops the row.
        assert await delete_instance_access(session, "u1")

    async with session_scope() as session:
        from sqlalchemy import select

        row = (
            await session.execute(
                select(InstanceAccess).where(InstanceAccess.discord_user_id == "u1")
            )
        ).scalar_one_or_none()
    assert row is None, "hard delete removed the access grant row"


@pytest.mark.asyncio
async def test_delete_access_missing_user_returns_false(db):
    async with session_scope() as session:
        assert await delete_instance_access(session, "nobody") is False
