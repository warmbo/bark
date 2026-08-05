"""
Announcements module v1.0.0 — post text or embeds to a chosen channel.

Provides:
- Dashboard action to send announcements from the Operate tab
- Configurable default announcement channel
- Optional embed mode for richer formatting
- /announce slash command for quick posting from Discord

Placeholders are not required here; announcement text is freeform.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import discord
from fastapi import Request

from modules.base import (
    BarkModule,
    CommandRegistration,
    EventRegistration,
    PageRegistration,
    PermissionDefinition,
)

logger = logging.getLogger("bark.modules.announcements")


class AnnouncementsModule(BarkModule):
    """Post announcements to a selected channel as text or embeds."""

    name = "announcements"
    version = "1.0.0"
    description = "Send text or embed announcements to a configurable channel"
    author = "ZENHAWX"

    def get_events(self) -> list[EventRegistration]:
        return []

    def get_dashboard_pages(self) -> list[PageRegistration]:
        return [
            PageRegistration(
                route="/guild/{guild_id}/modules/announcements",
                label="Announcements",
                icon="megaphone",
                category="community",
            )
        ]

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(name="announce", description="Send a text or embed announcement"),
        ]

    def get_permissions(self) -> list[PermissionDefinition]:
        return [
            PermissionDefinition(name="announcements.post", label="Post Announcements"),
        ]

    async def enable(self) -> None:
        self._logger.info("Enabling announcements module v%s", self.version)

    async def disable(self) -> None:
        self._logger.info("Disabling announcements module")

    def get_about(self) -> list[dict]:
        return [
            {
                "title": "What It Does",
                "description": "Lets moderators post announcements to a chosen channel from either the dashboard or a slash command, with an optional embed for polished formatting.",
            },
            {
                "title": "Defaults",
                "description": "You can save a default announcement channel for convenience. You can still override the channel per announcement.",
            },
            {
                "title": "How to Set Up",
                "description": "Enable the module, choose a default channel in Configure if you want, then post from Operate or with /announce.",
            },
        ]

    def get_settings_schema(self) -> dict:
        return {
            "type": "object",
            "description": "Configure announcement defaults.",
            "properties": {
                "default_channel": {
                    "type": "string",
                    "format": "channel_select",
                    "title": "Default Channel",
                    "description": "Optional default channel for announcements. You can still choose a channel when posting.",
                    "placeholder": "Select a channel…",
                },
            },
        }

    def get_actions(self) -> list[dict]:
        return [
            {
                "id": "post_announcement",
                "label": "Post announcement",
                "description": "Send a message or embed to a channel.",
                "endpoint": "post",
                "fields": [
                    {
                        "key": "channel_id",
                        "label": "Channel",
                        "type": "api_select",
                        "required": True,
                        "api": "/api/v1/guilds/{guild_id}/channels",
                        "value_key": "id",
                        "label_key": "name",
                        "group_key": "parent_name",
                        "placeholder": "Select a channel…",
                    },
                    {
                        "key": "title",
                        "label": "Title",
                        "type": "text",
                        "required": False,
                        "placeholder": "Optional embed title",
                    },
                    {
                        "key": "message",
                        "label": "Message",
                        "type": "textarea",
                        "rows": 10,
                        "maxLength": 2000,
                        "format_toolbar": True,
                        "required": True,
                        "placeholder": "Write the announcement here. Supports newlines.",
                    },
                    {
                        "key": "as_embed",
                        "label": "Send as embed",
                        "type": "boolean",
                        "required": False,
                        "placeholder": "Use embed formatting",
                    },
                    {
                        "key": "image_url",
                        "label": "Image URL",
                        "type": "text",
                        "required": False,
                        "placeholder": "Optional — also auto-detected from Image/Upload toolbar markdown",
                    },
                    {
                        "key": "video_url",
                        "label": "Video URL",
                        "type": "text",
                        "required": False,
                        "placeholder": "YouTube / Vimeo / TikTok / direct MP4 — shows Watch Video button in embed",
                    },
                ],
            }
        ]

    def get_api_routes(self):
        from fastapi import APIRouter  # local import to avoid module-level cost

        router = APIRouter(tags=["api-announcements"])

        @router.post("/guilds/{guild_id}/modules/announcements/post")
        async def post_announcement(request: Request, guild_id: str):
            from services.response import (
                api_error,
                api_forbidden,
                api_not_found,
                api_success,
                check_api_permission,
            )

            if not check_api_permission(request, "announcements.post", guild_id):
                return api_forbidden()

            guild_id = str(guild_id)
            try:
                data = await request.json()
            except Exception:
                return api_error("Invalid JSON body", status_code=400)

            channel_id = str(data.get("channel_id", "") or "").strip()
            title = str(data.get("title", "") or "")
            message = str(data.get("message", "") or "")
            as_embed = bool(data.get("as_embed", False))
            image_url = str(data.get("image_url", "") or "").strip()
            video_url = str(data.get("video_url", "") or "").strip()

            if not channel_id or not message.strip():
                return api_error("channel_id and message are required")

            bot = request.state.bot
            try:
                guild = bot.get_guild(int(guild_id))
            except Exception:
                guild = None
            if guild is None:
                return api_not_found("Guild")

            channel = guild.get_channel(int(channel_id))
            if channel is None:
                return api_error("Channel not found in this guild")

            image_url = image_url or None
            if not image_url and as_embed and message:
                m = re.search(r"!\[.*?\]\((https?://\S+)\)", message)
                if m:
                    image_url = m.group(1)

            description = message[:4096]
            if video_url and as_embed:
                vid = video_url.strip().rstrip("/")
                link = f"[Watch Video]({vid})"
                description = f"{description}\n\n{link}" if description else link

            try:
                if as_embed:
                    emb = discord.Embed(
                        title=title or None,
                        description=description or None,
                        color=discord.Color.blurple(),
                        timestamp=datetime.now(timezone.utc),
                    )
                    if image_url:
                        emb.set_image(url=image_url)
                    await channel.send(embed=emb)
                else:
                    if image_url:
                        emb = discord.Embed(color=discord.Color.blurple())
                        emb.set_image(url=image_url)
                        await channel.send(content=message[:2000], embed=emb)
                    else:
                        await channel.send(content=message[:2000])
            except discord.Forbidden:
                return api_error("Missing permission to send to that channel")
            except discord.HTTPException as exc:
                return api_error(f"Discord send failed: {exc.status}")

            return api_success({"sent": True})

        return router

    # ── Discord slash command ────────────────────────────

    def _make_announce_command(self):
        from discord import app_commands

        @app_commands.command(
            name="announce", description="Send a text or embed announcement to a channel"
        )
        @app_commands.default_permissions(manage_guild=True)
        @app_commands.describe(
            channel="Target announcement channel",
            title="Optional embed title",
            message="Announcement content",
            embed="Send as embed instead of plain text",
            image_url="Optional image URL to embed inline",
            video_url="Optional video URL — appended as Watch Video link in embeds",
        )
        async def announce_cmd(
            interaction: discord.Interaction,
            channel: discord.TextChannel,
            title: str | None = None,
            message: str = "",
            embed: bool = False,
            image_url: str | None = None,
            video_url: str | None = None,
        ):
            if interaction.guild is None:
                await interaction.response.send_message("Guild-only command.", ephemeral=True)
                return

            if not channel.permissions_for(interaction.guild.me).send_messages:
                await interaction.response.send_message(
                    "I cannot send messages to that channel.", ephemeral=True
                )
                return

            if not message.strip():
                await interaction.response.send_message("`message` is required.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)
            try:
                if embed:
                    announcement_embed = discord.Embed(
                        title=title or None,
                        description=message[:4096],
                        color=discord.Color.blurple(),
                        timestamp=datetime.now(timezone.utc),
                    )
                    if image_url:
                        announcement_embed.set_image(url=image_url)
                    if video_url:
                        vid = video_url.strip().rstrip("/")
                        link = f"[Watch Video]({vid})"
                        desc = announcement_embed.description or ""
                        announcement_embed.description = f"{desc}\n\n{link}" if desc else link
                    await channel.send(embed=announcement_embed)
                else:
                    if image_url:
                        img_emb = discord.Embed(color=discord.Color.blurple())
                        img_emb.set_image(url=image_url)
                        await channel.send(content=message[:2000], embed=img_emb)
                    else:
                        await channel.send(content=message[:2000])
                await interaction.followup.send(
                    f"Announcement sent to {channel.mention}.", ephemeral=True
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    "I do not have permission to send to that channel.", ephemeral=True
                )
            except discord.HTTPException as exc:
                await interaction.followup.send(f"Send failed: {exc.status}", ephemeral=True)

        return announce_cmd
