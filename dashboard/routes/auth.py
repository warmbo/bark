"""
Discord OAuth2 authentication routes.

Only enabled when BARK_OAUTH2_CLIENT_ID is set.
"""

from __future__ import annotations

import hmac
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
from services.instance_invites import authorize_instance_user

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


# Human-readable messages for ?auth_error= codes surfaced on the public
# landing page. NEVER redirect auth failures to /dashboard — it is auth-gated,
# so AuthMiddleware would bounce to /auth/login → Discord authorize → loop
# (observed 2026-08-06: uninvited user's login rejected, redirected to
# /dashboard?auth_error=invite_required, bounced back to Discord, repeat).
AUTH_ERROR_MESSAGES = {
    "denied": "Sign-in was cancelled.",
    "invalid_state": "Your sign-in session expired — please try again.",
    "no_code": "Discord didn't return a code — please try again.",
    "token_failed": "Discord rejected the sign-in — please try again.",
    "user_fetch_failed": "Couldn't load your Discord profile — please try again.",
    "guild_fetch_failed": "Couldn't load your servers — please try again.",
    "invite_required": "This Bark instance is invite-only. Ask the owner for an invite link.",
    "no_shared_guild": "You need to be a member of a server where Bark is installed to use the dashboard.",
    "oauth_required": "Sign-in isn't set up on this instance yet.",
}


def _auth_error_redirect(code: str) -> RedirectResponse:
    """Land auth failures on the PUBLIC landing page so the user sees the
    message instead of being bounced back into the Discord authorize loop."""
    return RedirectResponse(url=f"/?auth_error={code}", status_code=302)


@router.get("/login")
async def login(request: Request):
    """Redirect user to Discord OAuth2 authorize URL."""
    if not _oauth_enabled():
        logger.warning("OAuth2 login attempted but not configured")
        return RedirectResponse(url="/dashboard")

    # Already authenticated — never re-fire the Discord authorize flow (a
    # logged-in user hitting /auth/login would otherwise loop through Discord).
    if request.session.get("user"):
        return RedirectResponse(url="/dashboard", status_code=302)

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
        return _auth_error_redirect("denied")

    # Validate state (constant-time — avoids timing oracles on the token)
    saved_state = request.session.pop("oauth_state", None)
    if not state or not saved_state or not hmac.compare_digest(state, saved_state):
        logger.warning("OAuth state mismatch")
        return _auth_error_redirect("invalid_state")

    if not code:
        return _auth_error_redirect("no_code")

    # Exchange code for token. Timeout is essential — a hung Discord call
    # would otherwise stall the login request indefinitely (audit finding).
    async with httpx.AsyncClient(timeout=15.0) as client:
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
            return _auth_error_redirect("token_failed")

        token_json = token_resp.json()
        access_token = token_json["access_token"]

        # Fetch user info
        user_resp = await client.get(
            DISCORD_USER_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_resp.status_code != 200:
            logger.error("Failed to fetch user info: %s", user_resp.status_code)
            return _auth_error_redirect("user_fetch_failed")

        user = user_resp.json()

        # Fetch guilds
        guilds_resp = await client.get(
            DISCORD_GUILDS_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if guilds_resp.status_code != 200:
            logger.error("Failed to fetch Discord guilds: %s", guilds_resp.status_code)
            return _auth_error_redirect("guild_fetch_failed")
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

    # Only explicit owners and users who are members of a server where Bark
    # is installed can use this dashboard. Login is always required, but no
    # dashboard invite is needed for server members — invites are for adding
    # Bark to a server, not for dashboard access. Active hosted-instance
    # grants remain a fallback admission path.
    role = "viewer"
    async with session_scope() as session:
        is_owner = user["id"] in config.oauth2.owner_discord_ids
        invite_token = request.session.pop("instance_invite_token", None)
        shared_guild_ids = {str(g.get("id")) for g in guilds} & bot_guild_ids
        if not is_owner and not shared_guild_ids and not await authorize_instance_user(
            session,
            discord_user_id=user["id"],
            invite_token=invite_token,
        ):
            request.session.clear()
            logger.warning(
                "Rejected dashboard login for Discord user %s: not a member of any Bark server",
                user["id"],
            )
            return _auth_error_redirect("no_shared_guild")

        # Persist user to database and determine role
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
        # small for Discord users who belong to many servers. Resolve the
        # member's role IDs per guild from the bot's cache so per-server
        # "Ready to manage" gating (owner-configured moderator roles) works
        # without another Discord round-trip on every page load.
        roles_by_guild: dict[str, list[str]] = {}
        for guild in bot_from_state.guilds if bot_from_state is not None else []:
            member = guild.get_member(int(user["id"]))
            if member is not None:
                roles_by_guild[str(guild.id)] = [
                    str(role.id) for role in member.roles if role.id != guild.id
                ]
        await replace_user_guild_access(
            session,
            user["id"],
            guilds,
            roles_by_guild=roles_by_guild,
        )

    # Rotate the session on privilege change: the pre-auth cookie carried the
    # oauth_state (and possibly an invite token) — mint a fresh one with only
    # identity. Client-side signed cookies make fixation impractical, but
    # rotation is the standard hardening.
    request.session.clear()
    request.session["user"] = {
        "id": user["id"],
        "username": user.get("global_name") or user["username"],
        "display_name": user["username"],
        "avatar": _avatar_url(user),
        "discriminator": user.get("discriminator", "0"),
    }
    request.session["role"] = role

    logger.info("User %s authenticated via Discord OAuth2 — role=%s", user["id"], role)
    return RedirectResponse(url="/dashboard")


@router.get("/share/{token}")
async def accept_share_link(request: Request, token: str):
    """Stage a one-time invite token until the recipient completes Discord OAuth."""
    if not _oauth_enabled():
        return _auth_error_redirect("oauth_required")
    request.session["instance_invite_token"] = token
    return RedirectResponse(url="/auth/login")


@router.post("/logout")
async def logout(request: Request):
    """Clear session and redirect to dashboard."""
    request.session.clear()
    return RedirectResponse(url="/dashboard")


@router.get("/me")
async def me(request: Request):
    """Return current user info from session."""
    if not _oauth_enabled():
        # Permissive mode (OAuth not configured — local/test/dev): everyone is
        # treated as an authenticated admin so the dashboard renders without a
        # Discord login. The realtime/session guard depends on this.
        from services.response import api_success

        return api_success(
            {
                "authenticated": True,
                "user": {"id": "local", "username": "Local Admin", "display_name": "Local Admin"},
                "role": "admin",
                "guilds": [],
                "capabilities": [],
            }
        )
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
