"""
Welcome module v2.0.0 — customizable welcome/goodbye messages with optional embeds.

Provides:
- Configurable welcome messages posted to a Discord channel
- Configurable goodbye messages when members leave
- Optional welcome DM
- Optional embed presentation for welcome/goodbye messages
- Placeholders: {user}, {user.mention}, {user.id}, {server}, {member_count}

See docs/module-workspace.md for workspace layout contract.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord

from modules.base import (
    BarkModule,
    CommandRegistration,
    EventRegistration,
    PageRegistration,
    PermissionDefinition,
)

logger = logging.getLogger("bark.modules.welcome")


class WelcomeModule(BarkModule):
    """Customizable welcome and goodbye messages with optional embed formatting."""

    name = "welcome"
    version = "2.0.0"
    description = "Welcome messages, goodbye messages, and optional embeds for new members"
    author = "ZENHAWX"

    def get_events(self) -> list[EventRegistration]:
        return [
            EventRegistration("discord_member_join", handler="_on_member_join"),
            EventRegistration("discord_member_remove", handler="_on_member_remove"),
        ]

    def get_dashboard_pages(self) -> list[PageRegistration]:
        return [
            PageRegistration(
                route="/guild/{guild_id}/modules/welcome",
                label="Welcome",
                icon="hand",
                category="community",
            )
        ]

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(name="welcome", description="Preview or test welcome messages"),
        ]

    def get_about(self) -> list[dict]:
        return [
            {
                "title": "What It Does",
                "description": "Sends a custom welcome message to a channel when a new member joins, "
                "optionally sends a welcome DM, and sends a goodbye message when they leave. "
                "Each message can be sent as plain text or as an embed for richer formatting.",
            },
            {
                "title": "Message Templates",
                "description": "Use placeholders in your messages: "
                "`{user}` = username, `{user.mention}` = @mention, "
                "`{user.id}` = user ID, `{server}` = server name, `{member_count}` = current member count.",
            },
            {
                "title": "Embeds",
                "description": "Enable embeds to send polished welcome or goodbye embeds with your custom text. "
                "Embed descriptions support up to 4096 characters for longer messages.",
            },
            {
                "title": "How to Set Up",
                "description": "Enable the module, configure channels, write longer messages if needed, "
                "and toggle embeds on or off per message type in the Configuration tab.",
            },
        ]

    def get_settings_schema(self) -> dict:
        return {
            "type": "object",
            "description": "Configure welcome and goodbye messages, including optional embeds.",
            "properties": {
                "welcome_channel": {
                    "type": "string",
                    "format": "channel_select",
                    "title": "Welcome Channel",
                    "description": "Channel where new member welcome messages are posted. Leave empty to disable.",
                    "placeholder": "Select a channel...",
                },
                "welcome_message": {
                    "type": "string",
                    "format": "textarea",
                    "format_toolbar": True,
                    "title": "Welcome Message",
                    "description": "Message or embed description posted when someone joins. Supports {user}, {user.mention}, {server}, and {member_count}. `**bold**`, *italic*, `code`, ||spoiler||, ---",
                    "placeholder": "Welcome {user.mention} to {server}! We now have {member_count} members.",
                    "default": "Welcome {user.mention} to {server}!",
                    "rows": 10,
                    "maxLength": 2000,
                },
                "welcome_embed": {
                    "type": "boolean",
                    "title": "Send Welcome as Embed",
                    "description": "Post the welcome message as a Discord embed instead of plain text.",
                    "default": False,
                },
                "goodbye_channel": {
                    "type": "string",
                    "format": "channel_select",
                    "title": "Goodbye Channel",
                    "description": "Channel where goodbye messages are posted when members leave. Leave empty to disable.",
                    "placeholder": "Select a channel...",
                },
                "goodbye_message": {
                    "type": "string",
                    "format": "textarea",
                    "format_toolbar": True,
                    "title": "Goodbye Message",
                    "description": "Message or embed description posted when a member leaves. Supports {user}, {server}, and {member_count}. `**bold**`, *italic*, `code`, ||spoiler||, ---",
                    "placeholder": "Goodbye {user}, thanks for being part of {server}.",
                    "default": "Goodbye {user}, we will miss you.",
                    "rows": 10,
                    "maxLength": 2000,
                },
                "goodbye_embed": {
                    "type": "boolean",
                    "title": "Send Goodbye as Embed",
                    "description": "Post the goodbye message as a Discord embed instead of plain text.",
                    "default": False,
                },
                "goodbye_dm_enabled": {
                    "type": "boolean",
                    "title": "Send Goodbye DM",
                    "description": "Send a direct message to members when they leave.",
                    "default": False,
                },
                "goodbye_dm_message": {
                    "type": "string",
                    "format": "textarea",
                    "format_toolbar": True,
                    "title": "Goodbye DM Template",
                    "description": "DM sent when a member leaves. Supports {user}, {server}, and {member_count}. `**bold**`, *italic*, `code`, ||spoiler||, ---",
                    "placeholder": "Sorry to see you go, {user}. We hope to see you again in {server}.",
                    "default": "Goodbye {user}, thanks for being part of {server}!",
                    "rows": 10,
                    "maxLength": 2000,
                },
                "dm_enabled": {
                    "type": "boolean",
                    "title": "Send Welcome DM",
                    "description": "Send a direct message to new members when they join.",
                    "default": False,
                },
                "dm_message": {
                    "type": "string",
                    "format": "textarea",
                    "format_toolbar": True,
                    "title": "Welcome DM Template",
                    "description": "DM sent to new members. Supports {user}, {server}, and {member_count}. `**bold**`, *italic*, `code`, ||spoiler||, ---",
                    "placeholder": "Welcome to {server}! Check out the rules and say hello.",
                    "default": "Welcome to {server}! We are glad to have you.",
                    "rows": 10,
                    "maxLength": 2000,
                },
            },
        }

    async def enable(self) -> None:
        self._logger.info("Enabling welcome module v%s", self.version)

    async def disable(self) -> None:
        self._logger.info("Disabling welcome module")

    def get_permissions(self) -> list[PermissionDefinition]:
        return [
            PermissionDefinition(name="welcome.manage", label="Manage Welcome Settings"),
        ]

    # ── Message helpers ──────────────────────────────────

    def _format(self, template: str, member: discord.Member) -> str:
        """Replace placeholders in a message template."""
        if not template:
            return ""
        return (
            template.replace("{user}", str(member))
            .replace("{user.mention}", member.mention)
            .replace("{user.id}", str(member.id))
            .replace("{server}", member.guild.name)
            .replace("{member_count}", str(member.guild.member_count))
        )

    def _build_message(self, template: str, member: discord.Member, as_embed: bool, title: str):
        """Return either a formatted string or a Discord embed from a template."""
        text = self._format(template, member)
        if not as_embed:
            return text
        embed = discord.Embed(
            title=title,
            description=text[:4096],
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        return embed

    async def _send(self, target, content):
        """Send either a string or embed to a message target."""
        if content is None:
            return
        try:
            if isinstance(content, discord.Embed):
                await target.send(embed=content)
            else:
                await target.send(str(content)[:2000])
        except (discord.Forbidden, discord.HTTPException):
            pass

    # ── Event handlers ──────────────────────────────────

    async def _on_member_join(self, event_type: str, **data) -> None:
        member = data.get("member")
        if not member or member.bot:
            return

        config = await self.load_dashboard_config(member.guild.id)
        if not config:
            return

        # Guard: moderation module may have kicked/banned this member.
        if member.guild.get_member(member.id) is None:
            return

        # Welcome channel message
        ch_id = config.get("welcome_channel", "")
        if ch_id:
            channel = member.guild.get_channel(int(ch_id))
            if channel:
                message = self._build_message(
                    config.get("welcome_message", "Welcome {user.mention} to {server}!"),
                    member,
                    bool(config.get("welcome_embed")),
                    "Welcome!",
                )
                await self._send(channel, message)

        # Welcome DM
        dm_enabled = config.get("dm_enabled", False)
        if dm_enabled and member:
            dm_text = self._format(config.get("dm_message", "Welcome to {server}!"), member)
            if dm_text.strip():
                try:
                    await member.send(dm_text[:2000])
                except (discord.Forbidden, discord.HTTPException):
                    pass

    async def _on_member_remove(self, event_type: str, **data) -> None:
        member = data.get("member")
        if not member or member.bot:
            return

        config = await self.load_dashboard_config(member.guild.id)
        if not config:
            return

        ch_id = config.get("goodbye_channel", "")
        if not ch_id:
            return

        channel = member.guild.get_channel(int(ch_id))
        if not channel:
            return

        message = self._build_message(
            config.get("goodbye_message", "Goodbye {user}, we will miss you."),
            member,
            bool(config.get("goodbye_embed")),
            "Goodbye!",
        )
        await self._send(channel, message)

        dm_enabled = bool(config.get("goodbye_dm_enabled"))
        if dm_enabled:
            dm_text = self._format(
                config.get("goodbye_dm_message", "Goodbye {user}, we will miss you."), member
            )
            if dm_text.strip():
                try:
                    await member.send(dm_text[:2000])
                except (discord.Forbidden, discord.HTTPException):
                    pass

    # ── Slash command ───────────────────────────────────

    def _make_welcome_command(self):
        @discord.app_commands.command(name="welcome", description="Preview or test welcome message")
        @discord.app_commands.default_permissions(manage_guild=True)
        async def welcome_cmd(interaction: discord.Interaction):
            if not interaction.guild:
                return
            await interaction.response.defer(ephemeral=True)
            config = await self.load_dashboard_config(interaction.guild.id)

            embed = discord.Embed(
                title="Welcome Module Status",
                color=discord.Color.blurple(),
                timestamp=datetime.now(timezone.utc),
            )
            ch_id = config.get("welcome_channel", "")
            if ch_id and interaction.guild.get_channel(int(ch_id)):
                embed.add_field(name="Welcome Channel", value=f"<#{ch_id}>", inline=True)
            else:
                embed.add_field(name="Welcome Channel", value="Not configured", inline=True)

            welcome_embed = bool(config.get("welcome_embed"))
            template = config.get("welcome_message", "Welcome {user.mention} to {server}!")
            preview = template[:4000]
            embed.add_field(
                name=f"Welcome Preview ({'embed' if welcome_embed else 'text'})",
                value=preview or "Not configured",
                inline=False,
            )

            gb_id = config.get("goodbye_channel", "")
            if gb_id and interaction.guild.get_channel(int(gb_id)):
                embed.add_field(name="Goodbye Channel", value=f"<#{gb_id}>", inline=True)
            else:
                embed.add_field(name="Goodbye Channel", value="Not configured", inline=True)

            dm_enabled = config.get("dm_enabled", False)
            embed.add_field(
                name="Welcome DM", value="✅ Enabled" if dm_enabled else "❌ Disabled", inline=True
            )

            await interaction.followup.send(embed=embed, ephemeral=True)

        return welcome_cmd
