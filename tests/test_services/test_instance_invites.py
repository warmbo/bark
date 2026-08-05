"""Tests for hosted-instance invitation security and lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from database.engine import session_scope
from database.models.permissions import DashboardUser
from services.instance_invites import (
    create_instance_invite,
    is_instance_user_authorized,
    redeem_instance_invite,
    revoke_instance_access,
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
