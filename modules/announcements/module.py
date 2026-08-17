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

import asyncio
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

# Discord REST sends can stall (rate limits, API latency); cap them so a hung
# request cannot block the dashboard handler or the slash command forever.
_SEND_TIMEOUT_SECONDS = 10.0


async def _send_with_timeout(channel, *, content=None, embed=None) -> None:
    """Send a message with a hard timeout so a stalled Discord call fails fast."""
    await asyncio.wait_for(channel.send(content=content, embed=embed), timeout=_SEND_TIMEOUT_SECONDS)


def _full_width_spacer_url() -> str:
    """Public URL of an invisible wide spacer that forces Discord to render embeds full width.

    Discord sizes an embed by its widest intrinsic content. A transparent PNG with
    a 1600px intrinsic width makes Discord expand the embed to the full available
    width (capped at the channel's max embed width), while the 1px height keeps it
    invisible. Served from our own static directory so it is always fetchable by
    Discord.
    """
    from config import config

    base = config.dashboard.public_url.rstrip("/")
    return f"{base}/static/img/spacer-wide.png"


# Non-breaking spaces render as ordinary (invisible) width in Discord's embed
# text but are NOT collapsed or stripped the way zero-width characters are.
# U+200B (zero-width space) is discarded by the current client, which is why the
# old invisible-field trick stopped working.
_FULL_WIDTH_PAD = "\u00a0" * 160


def _force_full_width(embed: discord.Embed) -> None:
    """Force Discord to lay the embed out at full width.

    Discord renders text-only embeds in a narrow column. It only expands an embed
    to the full available width when the embed carries media (an image) or when it
    has fields laid out in a row. Three inline fields of non-breaking spaces
    survive the client sanitizer (unlike U+200B) while laying out as an invisible
    field row that stretches across the full width.
    """
    for _ in range(3):
        embed.add_field(name="\u00a0", value="\u00a0", inline=True)


def _pad_footer_full_width(embed: discord.Embed) -> None:
    """Pad the embed footer with invisible non-breaking spaces.

    An embed whose footer text is wider than the attached image (or the title /
    description) spans Discord's maximum embed width. This is the most reliable
    full-width trigger even when a small real image would otherwise shrink the
    embed to the image's own width.
    """
    base_text = embed.footer.text or "Bark"
    embed.set_footer(text=f"{base_text}{_FULL_WIDTH_PAD}")


def _parse_embed_color(raw: str | None) -> discord.Color:
    """Parse a #RRGGBB (or RRGGBB) color string, falling back to blurple.

    Discord accepts any 24-bit RGB color for embeds; invalid or empty values
    should not break posting, so they degrade to the brand accent.
    """
    if not raw:
        return discord.Color.blurple()
    value = str(raw).strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return discord.Color(int(value, 16))
    return discord.Color.blurple()


class AnnouncementsModule(BarkModule):
    """Post announcements to a selected channel as text or embeds."""

    name = "announcements"
    version = "1.0.0"
    description = "Send text or embed announcements to a configurable channel"
    author = "ZENHAWX"

    # Announcement defaults are optional conveniences; the module is fully
    # usable from the Operate tab and /announce without a Configure screen.
    show_configure_tab = False

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
                "description": f"Enable the module, choose a default channel in Configure if you want, then post from Operate or with /{self.command_group_name()} announce.",
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
                "default_embed_color": {
                    "type": "color",
                    "title": "Default Embed Color",
                    "description": "Accent color used for announcement embeds when no color is chosen at post time.",
                    "placeholder": "Accent color for the embed sidebar",
                    "default": "#5865F2",
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
                        "default": True,
                    },
                    {
                        "key": "embed_color",
                        "label": "Embed color",
                        "type": "color",
                        "required": False,
                        "placeholder": "Accent color for the embed sidebar and footer",
                        "default": "#5865F2",
                        "depends_on": {"field": "as_embed", "value": "true"},
                    },
                    {
                        "key": "media",
                        "label": "Media",
                        "type": "media_picker",
                        "required": False,
                        "placeholder": "Add images or video URLs — images embed inline, videos show a Watch Video link",
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
            embed_color = str(data.get("embed_color", "") or "").strip()
            if not embed_color:
                cfg = await self.load_dashboard_config(int(guild_id))
                embed_color = str((cfg or {}).get("default_embed_color", "") or "").strip()
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

            # Media picker payload: [{"type": "image"|"video", "url": "..."}]
            media_raw = data.get("media")
            if isinstance(media_raw, list):
                for item in media_raw:
                    if not isinstance(item, dict):
                        continue
                    url = str(item.get("url", "") or "").strip()
                    mtype = str(item.get("type", "image")).lower()
                    if not url:
                        continue
                    if mtype == "video":
                        video_url = video_url or url
                    else:
                        image_url = image_url or url

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
                        color=_parse_embed_color(embed_color),
                        timestamp=datetime.now(timezone.utc),
                    )
                    # Discord only expands an embed to full width when it carries
                    # an image wider than the text, or a row of fields. Stack all
                    # triggers so every embed spans the maximum width Discord
                    # allows: three non-breaking-space inline fields (they survive
                    # the sanitizer, unlike U+200B), a footer padded with invisible
                    # width (wins even against a small image), and a wide invisible
                    # image when no real image is attached.
                    _force_full_width(emb)
                    _pad_footer_full_width(emb)
                    if image_url:
                        emb.set_image(url=image_url)
                    else:
                        emb.set_image(url=_full_width_spacer_url())
                    await _send_with_timeout(channel, embed=emb)
                else:
                    if image_url:
                        emb = discord.Embed(color=discord.Color.blurple())
                        emb.set_image(url=image_url)
                        # A bare image embed hugs the image's width; pad the
                        # footer so even image-only posts span full width.
                        _force_full_width(emb)
                        _pad_footer_full_width(emb)
                        await _send_with_timeout(channel, content=message[:2000], embed=emb)
                    else:
                        await _send_with_timeout(channel, content=message[:2000])
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
            color="Embed accent color as #RRGGBB (embed mode only)",
            image_url="Optional image URL to embed inline",
            video_url="Optional video URL — appended as Watch Video link in embeds",
        )
        async def announce_cmd(
            interaction: discord.Interaction,
            channel: discord.TextChannel,
            title: str | None = None,
            message: str = "",
            embed: bool = False,
            color: str | None = None,
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
                        color=_parse_embed_color(color),
                        timestamp=datetime.now(timezone.utc),
                    )
                    # Full-width embeds: stack the row-of-fields trigger, a
                    # padded footer, and an image (real or wide invisible spacer).
                    _force_full_width(announcement_embed)
                    _pad_footer_full_width(announcement_embed)
                    if image_url:
                        announcement_embed.set_image(url=image_url)
                    else:
                        announcement_embed.set_image(url=_full_width_spacer_url())
                    if video_url:
                        vid = video_url.strip().rstrip("/")
                        link = f"[Watch Video]({vid})"
                        desc = announcement_embed.description or ""
                        announcement_embed.description = f"{desc}\n\n{link}" if desc else link
                    await _send_with_timeout(channel, embed=announcement_embed)
                else:
                    if image_url:
                        img_emb = discord.Embed(color=discord.Color.blurple())
                        img_emb.set_image(url=image_url)
                        # Pad the footer so the image embed spans full width too.
                        _force_full_width(img_emb)
                        _pad_footer_full_width(img_emb)
                        await _send_with_timeout(channel, content=message[:2000], embed=img_emb)
                    else:
                        await _send_with_timeout(channel, content=message[:2000])
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
