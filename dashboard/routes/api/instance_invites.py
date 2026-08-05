"""Owner-only API for administering hosted-instance access invitations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request

from config import config
from database.engine import session_scope
from services.instance_invites import (
    create_instance_invite,
    list_instance_access,
    list_instance_invites,
    revoke_instance_access,
    revoke_instance_invite,
)
from services.response import api_created, api_error, api_success

router = APIRouter(tags=["instance-invites"])


def _is_owner(request: Request) -> bool:
    user = request.session.get("user") or {}
    return (
        request.session.get("role") == "owner" and user.get("id") in config.oauth2.owner_discord_ids
    )


def _serialize_invite(invite) -> dict:
    return {
        "id": invite.id,
        "created_at": invite.created_at.isoformat() if invite.created_at else None,
        "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
        "redeemed_at": invite.redeemed_at.isoformat() if invite.redeemed_at else None,
        "redeemed_by_discord_id": invite.redeemed_by_discord_id,
        "revoked_at": invite.revoked_at.isoformat() if invite.revoked_at else None,
        "note": invite.note,
    }


def _serialize_access(access) -> dict:
    return {
        "discord_user_id": access.discord_user_id,
        "granted_at": access.granted_at.isoformat() if access.granted_at else None,
        "revoked_at": access.revoked_at.isoformat() if access.revoked_at else None,
    }


@router.get("/instance/invites")
async def list_invites(request: Request):
    if not _is_owner(request):
        return api_error("Owner access required", status_code=403)
    async with session_scope() as session:
        invites = await list_instance_invites(session)
    return api_success({"invites": [_serialize_invite(invite) for invite in invites]})


@router.get("/instance/access")
async def list_access(request: Request):
    if not _is_owner(request):
        return api_error("Owner access required", status_code=403)
    async with session_scope() as session:
        grants = await list_instance_access(session)
    return api_success({"access": [_serialize_access(grant) for grant in grants]})


@router.post("/instance/invites")
async def create_invite(request: Request):
    if not _is_owner(request):
        return api_error("Owner access required", status_code=403)
    try:
        data = await request.json()
    except ValueError:
        return api_error("Request body must be valid JSON")

    days = data.get("expires_in_days", 7)
    note = str(data.get("note", "")).strip()
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 30:
        return api_error("expires_in_days must be between 1 and 30")
    if len(note) > 240:
        return api_error("note must be 240 characters or fewer")

    async with session_scope() as session:
        invite, token = await create_instance_invite(
            session,
            created_by_discord_id=request.session["user"]["id"],
            expires_at=datetime.now(timezone.utc) + timedelta(days=days),
        )
        invite.note = note
        await session.flush()
        result = _serialize_invite(invite)
    result["share_url"] = f"{config.dashboard.public_url}/auth/share/{token}"
    return api_created(result)


@router.delete("/instance/invites/{invite_id}")
async def revoke_invite(request: Request, invite_id: int):
    if not _is_owner(request):
        return api_error("Owner access required", status_code=403)
    async with session_scope() as session:
        revoked = await revoke_instance_invite(session, invite_id)
    if not revoked:
        return api_error("Invite cannot be revoked", status_code=404)
    return api_success({"revoked": True})


@router.delete("/instance/access/{discord_user_id}")
async def revoke_access(request: Request, discord_user_id: str):
    if not _is_owner(request):
        return api_error("Owner access required", status_code=403)
    async with session_scope() as session:
        revoked = await revoke_instance_access(session, discord_user_id)
    if not revoked:
        return api_error("Active access grant not found", status_code=404)
    return api_success({"revoked": True})
