"""Speak module — `/bark speak <key>` outputs preset phrases.

Admins/mods preset named phrases in the dashboard (Modules → Speak →
Phrases tab); any member of the server can then trigger them with
`/bark speak <key>`. The phrase is posted to the channel as a normal
message, so only admins (or whoever the owner grants via this module's
Role Access) can add content.
"""

from __future__ import annotations

import logging
import re

import discord
from fastapi import Request

from modules.base import (
    BarkModule,
    CommandRegistration,
    PageRegistration,
    PermissionDefinition,
)

logger = logging.getLogger("bark.speak")

_KEY_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_MAX_TEXT = 1900  # Discord message limit is 2000; leave headroom


def validate_phrases(raw: object) -> tuple[dict[str, str] | None, str | None]:
    """Validate a phrases payload.

    Returns ``(phrases, None)`` on success or ``(None, error_message)``.
    Keys must be safe tokens (``^[a-zA-Z0-9_-]{1,64}$``) and values must be
    non-empty strings of at most ``_MAX_TEXT`` characters.
    """
    if not isinstance(raw, dict):
        return None, "phrases must be an object"
    phrases: dict[str, str] = {}
    for key, value in raw.items():
        key = str(key).strip()
        if not _KEY_RE.match(key):
            return (
                None,
                f"Invalid phrase key {key!r} — use letters, numbers, - or _ (max 64 chars)",
            )
        if not isinstance(value, str) or not value.strip():
            return None, f"Phrase {key!r} needs non-empty text"
        text = value.strip()
        if len(text) > _MAX_TEXT:
            return None, f"Phrase {key!r} is too long (max {_MAX_TEXT} chars)"
        phrases[key] = text
    return phrases, None


class SpeakModule(BarkModule):
    name = "speak"
    version = "1.0.0"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.description = (
            f"Preset phrases triggered by /{self.command_group_name()} speak "
            "— configured in the dashboard."
        )

    # ── Registration ──────────────────────────────────

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(
                name="speak",
                description="Say a preset phrase (keys are configured in the dashboard)",
            )
        ]

    def get_dashboard_pages(self) -> list[PageRegistration]:
        return [
            PageRegistration(
                route="/guild/{guild_id}/modules/speak",
                label="Speak",
                icon="message-square",
                category="community",
            )
        ]

    def get_permissions(self) -> list[PermissionDefinition]:
        return [
            PermissionDefinition(
                name="speak.manage",
                label="Manage speak phrases",
                description="Add, edit, and remove preset phrases in the dashboard",
            )
        ]

    def get_about(self) -> list[dict]:
        return [
            {
                "title": "Speak",
                "description": (
                    f"Preset phrases your members can trigger with "
                    f"/{self.command_group_name()} speak <key>. Only admins (or anyone the owner "
                    "grants via Role Access) can edit the phrases — everyone "
                    "else can trigger them."
                ),
            }
        ]

    # ── Helpers ───────────────────────────────────────

    async def _load_phrases(self, guild_id: int) -> dict[str, str]:
        try:
            config = await self.load_dashboard_config(guild_id)
        except Exception:
            logger.exception("speak: failed to load config for guild %s", guild_id)
            return {}
        phrases = config.get("phrases")
        return phrases if isinstance(phrases, dict) else {}

    # ── Command ───────────────────────────────────────

    def _make_speak_command(self):
        @discord.app_commands.command(
            name="speak",
            description="Say a preset phrase (keys are configured in the dashboard)",
        )
        @discord.app_commands.describe(
            key="The phrase key, e.g. word1 or phrase2"
        )
        async def speak_cmd(interaction: discord.Interaction, key: str):
            guild_id = interaction.guild_id
            if guild_id is None:
                await interaction.response.send_message(
                    "This command only works inside a server.", ephemeral=True
                )
                return

            phrases = await self._load_phrases(guild_id)
            text = phrases.get(key.strip())

            if text is None:
                available = sorted(phrases.keys())
                message = f"Unknown phrase `{key}`."
                if available:
                    shown = ", ".join(f"`{k}`" for k in available[:25])
                    if len(available) > 25:
                        shown += f" and {len(available) - 25} more"
                    message += f" Available keys: {shown}."
                else:
                    message += (
                        " No phrases configured yet — an admin can add them "
                        "in the dashboard under Modules → Speak → Phrases."
                    )
                await interaction.response.send_message(message, ephemeral=True)
                return

            if not str(text).strip():
                await interaction.response.send_message(
                    f"Phrase `{key}` is empty — an admin should fix it in the dashboard.",
                    ephemeral=True,
                )
                return

            await interaction.response.send_message(str(text))

        return speak_cmd

    # ── Dashboard API ─────────────────────────────────

    def get_api_routes(self):
        from fastapi import APIRouter

        from services.response import (
            api_error,
            api_success,
            check_api_permission,
            get_module_min_role,
        )

        router = APIRouter(tags=["module-speak"])

        async def _require_manage(request: Request, guild_id: str) -> bool:
            await get_module_min_role("speak", guild_id)
            return check_api_permission(request, "speak.manage", guild_id)

        @router.get("/guilds/{guild_id}/modules/speak/phrases")
        async def get_phrases(request: Request, guild_id: str):
            if not await _require_manage(request, guild_id):
                return api_error("Insufficient permissions", status_code=403)
            phrases = await self._load_phrases(int(guild_id))
            return api_success({"phrases": phrases})

        @router.put("/guilds/{guild_id}/modules/speak/phrases")
        async def save_phrases(request: Request, guild_id: str):
            if not await _require_manage(request, guild_id):
                return api_error("Insufficient permissions", status_code=403)
            try:
                data = await request.json()
            except Exception:
                return api_error("Invalid JSON body", status_code=400)

            phrases, error = validate_phrases(data.get("phrases"))
            if error is not None:
                return api_error(error, status_code=400)

            config = await self.load_dashboard_config(int(guild_id))
            config["phrases"] = phrases
            await self.save_dashboard_config(int(guild_id), config)
            logger.info("Saved %d speak phrase(s) for guild %s", len(phrases), guild_id)
            return api_success({"saved": len(phrases)})

        return router

    # ── Lifecycle ─────────────────────────────────────

    async def enable(self) -> None:
        pass

    async def disable(self) -> None:
        pass
