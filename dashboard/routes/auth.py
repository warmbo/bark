"""
Discord OAuth2 authentication routes.

Only enabled when BARK_OAUTH2_CLIENT_ID is set.
"""

from __future__ import annotations

import logging
import secrets
import urllib.parse
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from config import config
from database.engine import session_scope
from database.models.permissions import DashboardUser
from services.dashboard_access import (
    derive_dashboard_role,
    get_user_guild_access,
    replace_user_guild_access,
    resolve_dashboard_role,
)

logger = logging.getLogger("bark.dashboard.auth")

DISCORD_AUTHORIZE_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"
DISCORD_GUILDS_URL = "https://discord.com/api/users/@me/guilds"

SCOPES = "identify guilds"

router = APIRouter(tags=["auth"], prefix="/auth")


def _oauth_enabled() -> bool:
    """Return True when Discord OAuth2 is configured."""
    return config.oauth2.enabled


@router.get("/login")
async def login(request: Request):
    """Redirect user to Discord OAuth2 authorize URL."""
    if not _oauth_enabled():
        logger.warning("OAuth2 login attempted but not configured")
        return RedirectResponse(url="/dashboard")

    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state

    params = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": config.oauth2.client_id,
            "redirect_uri": config.oauth2.redirect_uri,
            "scope": SCOPES,
            "state": state,
        }
    )
    redirect_url = f"{DISCORD_AUTHORIZE_URL}?{params}"
    return RedirectResponse(url=redirect_url)


@router.get("/callback")
async def callback(
    request: Request, code: str | None = None, state: str | None = None, error: str | None = None
):
    """Handle Discord OAuth2 callback, exchange code for token, create session."""
    if not _oauth_enabled():
        return RedirectResponse(url="/dashboard")

    # Check for error from Discord
    if error:
        logger.warning("Discord OAuth error: %s", error)
        return RedirectResponse(url="/dashboard?auth_error=denied")

    # Validate state
    saved_state = request.session.pop("oauth_state", None)
    if not state or not saved_state or state != saved_state:
        logger.warning("OAuth state mismatch")
        return RedirectResponse(url="/dashboard?auth_error=invalid_state")

    if not code:
        return RedirectResponse(url="/dashboard?auth_error=no_code")

    # Exchange code for token
    async with httpx.AsyncClient() as client:
        token_data = {
            "client_id": config.oauth2.client_id,
            "client_secret": config.oauth2.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.oauth2.redirect_uri,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        token_resp = await client.post(
            DISCORD_TOKEN_URL,
            data=token_data,
            headers=headers,
        )

        if token_resp.status_code != 200:
            # Log status only — the body can contain provider error details but
            # never the exchange secret; keep it out of logs to avoid leakage.
            logger.error("Token exchange failed with status %s", token_resp.status_code)
            return RedirectResponse(url="/dashboard?auth_error=token_failed")

        token_json = token_resp.json()
        access_token = token_json["access_token"]

        # Fetch user info
        user_resp = await client.get(
            DISCORD_USER_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_resp.status_code != 200:
            logger.error("Failed to fetch user info: %s", user_resp.status_code)
            return RedirectResponse(url="/dashboard?auth_error=user_fetch_failed")

        user = user_resp.json()

        # Fetch guilds
        guilds_resp = await client.get(
            DISCORD_GUILDS_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if guilds_resp.status_code != 200:
            logger.error("Failed to fetch Discord guilds: %s", guilds_resp.status_code)
            return RedirectResponse(url="/dashboard?auth_error=guild_fetch_failed")
        guilds = guilds_resp.json()

    # Store user info in session
    request.session["user"] = {
        "id": user["id"],
        "username": user.get("global_name") or user["username"],
        "display_name": user["username"],
        "avatar": _avatar_url(user),
        "discriminator": user.get("discriminator", "0"),
    }

    bot_from_state = getattr(request.app.state, "bot", None)
    bot_guild_ids = (
        {str(g.id) for g in bot_from_state.guilds} if bot_from_state is not None else set()
    )
    derived_role = derive_dashboard_role(guilds, bot_guild_ids)

    # Persist user to database and determine role
    role = "viewer"
    async with session_scope() as session:
        # Check if this user already has a record
        existing = (
            await session.execute(
                select(DashboardUser).where(DashboardUser.discord_id == user["id"])
            )
        ).scalar_one_or_none()

        role = resolve_dashboard_role(
            user["id"],
            config.oauth2.owner_discord_ids,
            derived_role,
            existing.role if existing else None,
        )

        if existing:
            # Update existing record
            existing.username = user.get("global_name") or user["username"]
            existing.avatar_url = _avatar_url(user) or ""
            existing.last_login = datetime.now(timezone.utc)
            existing.role = role
        else:
            session.add(
                DashboardUser(
                    discord_id=user["id"],
                    username=user.get("global_name") or user["username"],
                    avatar_url=_avatar_url(user) or "",
                    role=role,
                    last_login=datetime.now(timezone.utc),
                )
            )
            await session.flush()

        # Keep the complete guild snapshot server-side. Cookie sessions are too
        # small for Discord users who belong to many servers.
        await replace_user_guild_access(session, user["id"], guilds)

    request.session["role"] = role

    logger.info("User %s authenticated via Discord OAuth2 — role=%s", user["id"], role)
    return RedirectResponse(url="/dashboard")


@router.post("/logout")
async def logout(request: Request):
    """Clear session and redirect to dashboard."""
    request.session.clear()
    return RedirectResponse(url="/dashboard")


@router.get("/me")
async def me(request: Request):
    """Return current user info from session."""
    if not _oauth_enabled():
        from services.response import api_success

        return api_success({"authenticated": False})
    user = request.session.get("user")
    guilds = []
    if user is not None:
        async with session_scope() as session:
            rows = await get_user_guild_access(session, user["id"])
        guilds = [
            {
                "id": row.guild_id,
                "name": row.name,
                "icon": (
                    f"https://cdn.discordapp.com/icons/{row.guild_id}/{row.icon_hash}.png"
                    if row.icon_hash
                    else None
                ),
                "can_manage": row.can_manage,
            }
            for row in rows
        ]
    from services.response import api_success, get_capabilities

    return api_success(
        {
            "authenticated": user is not None,
            "user": user,
            "role": request.session.get("role", "viewer"),
            "guilds": guilds,
            "capabilities": get_capabilities(request),
        }
    )


def _avatar_url(user: dict) -> str | None:
    """Build Discord CDN avatar URL from user data."""
    avatar_hash = user.get("avatar")
    if not avatar_hash:
        return None
    return f"https://cdn.discordapp.com/avatars/{user['id']}/{avatar_hash}.png"
