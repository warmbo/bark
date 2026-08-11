"""First-time setup: write Bark's ``.env`` from the dashboard.

The systemd unit (and ``run.sh``) load ``.env`` from the repository root as
``EnvironmentFile`` — so a fresh install can boot the setup server with no
configuration at all, collect credentials in the browser, and have this
service produce a proper ``.env`` for them.

The file is written with restrictive permissions because it contains the
bot token.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("bark.setup")

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Keys the setup wizard is allowed to write. Everything else is left alone —
# the wizard is a bootstrap, not a full config editor. Commands are global
# slash commands under /bark — there is intentionally no prefix setting.
SETUP_KEYS = (
    "BARK_BOT_TOKEN",
    "BARK_PUBLIC_URL",
    "BARK_OAUTH2_CLIENT_ID",
    "BARK_OAUTH2_CLIENT_SECRET",
    "BARK_OAUTH2_REDIRECT_URI",
    "BARK_OWNER_DISCORD_IDS",
)

_NEEDS_QUOTING = re.compile(r'[\s#"\']')


def _escape(value: str) -> str:
    """dotenv-style value escaping: quote when it contains special chars."""
    if _NEEDS_QUOTING.search(value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


class SetupError(ValueError):
    """Invalid or impossible setup request."""


def env_file_path() -> Path:
    """The repository-root ``.env`` that systemd/run.sh load at boot."""
    return _REPO_ROOT / ".env"


def is_configured() -> bool:
    """True when a .env already exists (setup is a one-time bootstrap)."""
    return env_file_path().exists()


def _validate(payload: dict) -> dict:
    """Validate + normalize a setup payload, mirroring config.validate_startup."""
    token = str(payload.get("token") or "").strip()
    if not token:
        raise SetupError("A Discord bot token is required")
    if len(token.split(".")) != 3:
        raise SetupError(
            "That doesn't look like a Discord bot token — it should have "
            "three dot-separated parts (e.g. MTEz...xxxx.yyyy-zzzz)"
        )

    public_url = str(payload.get("public_url") or "").strip().rstrip("/")
    if not public_url:
        raise SetupError("A public dashboard URL is required (e.g. https://bark.example.com)")
    if not public_url.startswith(("http://", "https://")):
        raise SetupError("The public URL must start with http:// or https://")

    client_id = str(payload.get("client_id") or "").strip()
    client_secret = str(payload.get("client_secret") or "").strip()
    redirect_uri = str(payload.get("redirect_uri") or "").strip().rstrip("/")
    owner_ids = str(payload.get("owner_ids") or "").strip()

    oauth_requested = bool(client_id or client_secret or redirect_uri or owner_ids)
    if oauth_requested and not (client_id and client_secret):
        raise SetupError(
            "Discord OAuth needs both the client ID and client secret — set "
            "both, or leave them all empty to skip dashboard login for now"
        )
    if client_id and not redirect_uri:
        redirect_uri = f"{public_url}/auth/callback"
    if client_id and redirect_uri and not redirect_uri.startswith(("http://", "https://")):
        raise SetupError("The redirect URI must start with http:// or https://")
    if client_id and not owner_ids:
        raise SetupError(
            "BARK_OWNER_DISCORD_IDS is required when OAuth is enabled — "
            "comma-separated Discord user IDs who administer this instance"
        )

    values = {
        "BARK_BOT_TOKEN": token,
        "BARK_PUBLIC_URL": public_url,
    }
    if client_id:
        values["BARK_OAUTH2_CLIENT_ID"] = client_id
        values["BARK_OAUTH2_CLIENT_SECRET"] = client_secret
        values["BARK_OAUTH2_REDIRECT_URI"] = redirect_uri
        values["BARK_OWNER_DISCORD_IDS"] = owner_ids
    return values


def _render_env(values: dict) -> str:
    lines = []
    for key in SETUP_KEYS:
        if key in values and values[key]:
            lines.append(f"{key}={_escape(str(values[key]))}")
    return "\n".join(lines) + "\n"


def write_env(payload: dict) -> Path:
    """Validate the payload and write ``.env`` (refuses to overwrite)."""
    if is_configured():
        raise SetupError(
            "A .env file already exists — this instance is already configured. "
            "Delete it first to re-run setup."
        )
    values = _validate(payload)
    path = env_file_path()
    try:
        path.write_text(_render_env(values), encoding="utf-8")
        os.chmod(path, 0o600)
    except OSError as exc:
        raise SetupError(f"Could not write .env: {exc}") from exc
    logger.info("First-time setup wrote %s with %d settings", path, len(values))
    return path
