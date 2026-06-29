"""
Logging module for Bark v2.0.

Monitors: message edits, message deletes, file uploads, member joins/leaves,
moderation actions, voice state changes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord

from modules.base import (
    BarkModule,
    CommandRegistration,
    EventRegistration,
    PageRegistration,
    PermissionDefinition,
)
from database.engine import session_scope
from database.models.logging import LogConfig
from database.models.attachments import FileAttachment
from database.models.voice import VoiceSession

if TYPE_CHECKING:
    from bot.client import BarkBot

logger = logging.getLogger("bark.modules.logging")

EVENT_TYPES = {
    "message_edit": "Message Edits",
    "message_delete": "Message Deletes",
    "file_upload": "File Uploads",
    "member_join": "Member Joins",
    "member_leave": "Member Leaves",
    "moderation": "Moderation Actions",
    "voice_state": "Voice State Changes",
}


def _format_size(size_bytes: int) -> str:
    """Format byte size into human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


class LoggingModule(BarkModule):
    """Comprehensive event and file logging for server activity."""

    name = "logging"
    version = "2.0.0"
    description = (
        "Log message edits, deletes, file uploads, member joins/leaves, "
        "moderation actions, and voice state with full attachment tracking"
    )
    author = "ZENHAWX"

    def __init__(self, bot: BarkBot) -> None:
        super().__init__(bot)
        self._listeners: dict[str, callable] = {}

    # ── Registration ──────────────────────────────────

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(name="logsetup", description="Set up logging channels"),
            CommandRegistration(name="logstatus", description="View logging configuration"),
            CommandRegistration(name="logfiles", description="Search recent file uploads"),
        ]

    def get_events(self) -> list[EventRegistration]:
        return [
            EventRegistration(event_name="on_message"),
            EventRegistration(event_name="on_message_edit"),
            EventRegistration(event_name="on_message_delete"),
            EventRegistration(event_name="on_member_join"),
            EventRegistration(event_name="on_member_remove"),
            EventRegistration(event_name="on_voice_state_update"),
        ]

    def get_dashboard_pages(self) -> list[PageRegistration]:
        return [
            PageRegistration(
                route="/guild/{guild_id}/settings",
                label="Logging Settings",
                icon="📝",
                parent="settings",
            ),
        ]

    def get_permissions(self) -> list[PermissionDefinition]:
        return [
            PermissionDefinition(
                name="logging.configure",
                label="Configure Logging",
                description="Set up logging channels",
            ),
            PermissionDefinition(
                name="logging.files",
                label="View File Logs",
                description="Search and view file upload logs",
            ),
        ]

    def get_settings_schema(self) -> dict:
        return {
            "type": "object",
            "description": "Configure which server events are logged and which channels they go to. "
                           "Each event type can be sent to a different text channel.",
            "properties": {
                event_type: {
                    "type": "object",
                    "title": label,
                    "description": {
                        "message_edit": "Logs when a message is edited, showing before/after content.",
                        "message_delete": "Logs when a message is deleted, including content and attachments.",
                        "file_upload": "Logs when files are uploaded (images, documents, etc.) with download URLs.",
                        "member_join": "Logs when a new member joins the server.",
                        "member_leave": "Logs when a member leaves or is removed from the server.",
                        "moderation": "Logs moderation actions (warn, kick, ban, etc.).",
                        "voice_state": "Logs voice channel joins, leaves, and moves.",
                    }.get(event_type, f"Logging config for {event_type}"),
                    "properties": {
                        "channel_id": {
                            "type": "string",
                            "title": "Channel ID",
                            "placeholder": "123456789012345678",
                            "description": "The Discord channel ID where these logs will be posted. "
                                           "Right-click a channel → Copy ID to get this.",
                        },
                        "enabled": {
                            "type": "boolean",
                            "title": "Enabled",
                            "description": "Turn logging for this event type on or off.",
                        },
                    },
                }
                for event_type, label in EVENT_TYPES.items()
            },
        }

    # ── Lifecycle ─────────────────────────────────────

    async def enable(self) -> None:
        self._logger.info("Enabling logging module v%s", self.version)

        self.bot.add_listener(self._on_message, "on_message")
        self.bot.add_listener(self._on_message_edit, "on_message_edit")
        self.bot.add_listener(self._on_message_delete, "on_message_delete")
        self.bot.add_listener(self._on_member_join, "on_member_join")
        self.bot.add_listener(self._on_member_remove, "on_member_remove")
        self.bot.add_listener(self._on_voice_state_update, "on_voice_state_update")

        if hasattr(self.bot, "tree"):
            self.bot.tree.add_command(self._make_logsetup_command())
            self.bot.tree.add_command(self._make_logstatus_command())
            self.bot.tree.add_command(self._make_logfiles_command())

    async def disable(self) -> None:
        self._logger.info("Disabling logging module")
        self._listeners.clear()
        if hasattr(self.bot, "tree"):
            self.bot.tree.remove_command("logsetup")
            self.bot.tree.remove_command("logstatus")
            self.bot.tree.remove_command("logfiles")

    # ── Commands ──────────────────────────────────────

    def _make_logsetup_command(self):
        @discord.app_commands.command(name="logsetup", description="Configure logging channel")
        @discord.app_commands.default_permissions(manage_guild=True)
        async def logsetup(
            interaction: discord.Interaction,
            event_type: str,
            channel: discord.TextChannel,
            enabled: bool = True,
        ):
            await self._cmd_logsetup(interaction, event_type, channel, enabled)
        return logsetup

    def _make_logstatus_command(self):
        @discord.app_commands.command(name="logstatus", description="View logging configuration")
        async def logstatus(interaction: discord.Interaction):
            await self._cmd_logstatus(interaction)
        return logstatus

    def _make_logfiles_command(self):
        @discord.app_commands.command(
            name="logfiles",
            description="Search recent file uploads by member or type",
        )
        @discord.app_commands.default_permissions(manage_guild=True)
        async def logfiles(
            interaction: discord.Interaction,
            member: discord.Member | None = None,
            file_type: str | None = None,
            limit: int = 10,
        ):
            await self._cmd_logfiles(interaction, member, file_type, limit)
        return logfiles

    async def _cmd_logsetup(
        self,
        interaction: discord.Interaction,
        event_type: str,
        channel: discord.TextChannel,
        enabled: bool,
    ) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)

        if event_type not in EVENT_TYPES:
            valid = ", ".join(EVENT_TYPES.keys())
            await interaction.followup.send(
                f"Invalid event type. Valid: {valid}", ephemeral=True
            )
            return

        from sqlalchemy import select

        async with session_scope() as session:
            result = await session.execute(
                select(LogConfig).where(
                    LogConfig.guild_id == interaction.guild.id,
                    LogConfig.event_type == event_type,
                )
            )
            config = result.scalar_one_or_none()

            if config is None:
                config = LogConfig(
                    guild_id=interaction.guild.id,
                    event_type=event_type,
                    channel_id=str(channel.id),
                    enabled=enabled,
                )
                session.add(config)
            else:
                config.channel_id = str(channel.id)
                config.enabled = enabled
            await session.commit()

        await interaction.followup.send(
            f"✅ {EVENT_TYPES[event_type]} → #{channel.name} ({'enabled' if enabled else 'disabled'})",
            ephemeral=True,
        )

    async def _cmd_logstatus(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)

        from sqlalchemy import select, func

        async with session_scope() as session:
            result = await session.execute(
                select(LogConfig).where(LogConfig.guild_id == interaction.guild.id)
            )
            configs = result.scalars().all()

            # Count total files logged
            file_count = await session.execute(
                select(func.count(FileAttachment.id))
                .where(FileAttachment.guild_id == interaction.guild.id)
            )
            total_files = file_count.scalar() or 0

            if not configs:
                await interaction.followup.send(
                    "No logging channels configured. Use `/logsetup` to set them up.",
                    ephemeral=True,
                )
                return

            embed = discord.Embed(
                title="Logging Configuration",
                color=discord.Color.blurple(),
            )

            for config in configs:
                channel = interaction.guild.get_channel(int(config.channel_id))
                label = EVENT_TYPES.get(config.event_type, config.event_type)
                status = "✅" if config.enabled else "❌"
                channel_name = f"#{channel.name}" if channel else "deleted-channel"
                embed.add_field(
                    name=f"{status} {label}",
                    value=f"Channel: {channel_name}",
                    inline=False,
                )

            if total_files:
                embed.set_footer(text=f"{total_files} files logged to database")

            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _cmd_logfiles(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None,
        file_type: str | None,
        limit: int,
    ) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)

        from sqlalchemy import select, desc, and_

        query = (
            select(FileAttachment)
            .where(FileAttachment.guild_id == interaction.guild.id)
        )
        if member is not None:
            query = query.where(FileAttachment.author_id == str(member.id))
        if file_type is not None:
            query = query.where(FileAttachment.content_type.like(f"{file_type}%"))
        query = query.order_by(desc(FileAttachment.created_at)).limit(min(limit, 50))

        async with session_scope() as session:
            result = await session.execute(query)
            files = result.scalars().all()

            if not files:
                await interaction.followup.send("No matching files found.", ephemeral=True)
                return

            embed = discord.Embed(
                title=f"Recent File Uploads ({len(files)})",
                color=discord.Color.blurple(),
            )

            for f in files:
                icon = "🖼" if f.is_image else "📄"
                embed.add_field(
                    name=f"{icon} {f.filename}",
                    value=(
                        f"**By:** {f.author_tag}\n"
                        f"**Size:** {_format_size(f.file_size)}\n"
                        f"**Type:** `{f.content_type}`\n"
                        f"**Uploaded:** <t:{int(f.created_at.timestamp())}:R>\n"
                        f"**URL:** [Download]({f.file_url})"
                    ),
                    inline=False,
                )

            await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Event Handlers ────────────────────────────────

    async def _get_log_channel(self, guild_id: int, event_type: str) -> discord.TextChannel | None:
        from sqlalchemy import select

        async with session_scope() as session:
            result = await session.execute(
                select(LogConfig).where(
                    LogConfig.guild_id == guild_id,
                    LogConfig.event_type == event_type,
                    LogConfig.enabled == True,
                )
            )
            config = result.scalar_one_or_none()
        if config is None:
            return None
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return None
        return guild.get_channel(int(config.channel_id))

    async def _send_log_embed(
        self,
        channel: discord.TextChannel,
        title: str,
        description: str,
        color: discord.Color = discord.Color.blurple(),
        fields: list[tuple[str, str, bool]] | None = None,
        thumbnail: str | None = None,
        files_to_send: list[discord.File] | None = None,
    ) -> None:
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        if fields:
            for name, value, inline in fields:
                embed.add_field(name=name, value=value, inline=inline)
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        try:
            kwargs = {"embed": embed}
            if files_to_send:
                kwargs["files"] = files_to_send
            await channel.send(**kwargs)
        except discord.Forbidden:
            logger.warning("Cannot send log embed to channel %s", channel.id)

    # ── File Upload Tracking ──────────────────────────

    async def _on_message(self, message: discord.Message) -> None:
        """Track file attachments and log them."""
        if message.author.bot or not message.guild:
            return
        if not message.attachments:
            return

        channel = await self._get_log_channel(message.guild.id, "file_upload")
        guild_id = message.guild.id

        for attachment in message.attachments:
            is_image = attachment.content_type and attachment.content_type.startswith("image/")
            size_str = _format_size(attachment.size)

            # Persist to database
            async with session_scope() as session:
                session.add(FileAttachment(
                    guild_id=guild_id,
                    channel_id=str(message.channel.id),
                    message_id=str(message.id),
                    author_id=str(message.author.id),
                    author_tag=str(message.author),
                    filename=attachment.filename,
                    file_url=attachment.url,
                    file_size=attachment.size,
                    content_type=attachment.content_type or "application/octet-stream",
                    is_image=is_image,
                ))
                await session.commit()

            # Send log embed if configured
            if channel is not None:
                icon = "🖼" if is_image else "📄"
                await self._send_log_embed(
                    channel,
                    f"{icon} File Uploaded",
                    f"in {message.channel.mention}",
                    color=discord.Color.green(),
                    fields=[
                        ("Author", message.author.mention, True),
                        ("Channel", message.channel.mention, True),
                        ("Filename", attachment.filename, True),
                        ("Size", size_str, True),
                        ("Type", f"`{attachment.content_type or 'unknown'}`", True),
                        ("URL", f"[Download]({attachment.url})", True),
                    ],
                    thumbnail=attachment.url if is_image else None,
                )

    async def _on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.author.bot or before.content == after.content:
            return
        if not before.guild:
            return

        channel = await self._get_log_channel(before.guild.id, "message_edit")
        if channel is None:
            return

        fields = [
            ("Author", before.author.mention, True),
            ("Channel", before.channel.mention, True),
            ("Message ID", f"`{before.id}`", True),
        ]

        # Show before/after content
        if before.content:
            fields.append(("Before", before.content[:1000] or "*no content*", False))
        if after.content:
            fields.append(("After", after.content[:1000] or "*no content*", False))

        # Show attachment changes
        if before.attachments or after.attachments:
            before_files = ", ".join(a.filename for a in before.attachments) or "*none*"
            after_files = ", ".join(a.filename for a in after.attachments) or "*none*"
            if before_files != after_files:
                fields.append(("Files Before", before_files, False))
                fields.append(("Files After", after_files, False))

        await self._send_log_embed(
            channel, "✏️ Message Edited",
            f"in {before.channel.mention}",
            color=discord.Color.blue(),
            fields=fields,
        )

    async def _on_message_delete(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not message.guild:
            return

        channel = await self._get_log_channel(message.guild.id, "message_delete")
        if channel is None:
            return

        fields = [
            ("Author", message.author.mention, True),
            ("Channel", message.channel.mention, True),
            ("Message ID", f"`{message.id}`", True),
        ]

        if message.content:
            fields.append(("Content", message.content[:1000] or "*no content*", False))

        # Include attachment info in delete logs
        if message.attachments:
            file_list = "\n".join(
                f"[{a.filename}]({a.url}) ({_format_size(a.size)})"
                for a in message.attachments
            )
            fields.append(("Attachments", file_list, False))

        await self._send_log_embed(
            channel, "🗑️ Message Deleted",
            f"in {message.channel.mention}",
            color=discord.Color.red(),
            fields=fields,
        )

    async def _on_member_join(self, member: discord.Member) -> None:
        channel = await self._get_log_channel(member.guild.id, "member_join")
        if channel is None:
            return

        account_age = (discord.utils.utcnow() - member.created_at).days
        await self._send_log_embed(
            channel, "📥 Member Joined", member.mention,
            color=discord.Color.green(),
            fields=[
                ("User", f"{member} ({member.id})", True),
                ("Account Age", f"{account_age} days", True),
                ("Account Created", f"<t:{int(member.created_at.timestamp())}:R>", True),
                ("Member Count", str(member.guild.member_count), True),
            ],
            thumbnail=member.display_avatar.url,
        )

    async def _on_member_remove(self, member: discord.Member) -> None:
        channel = await self._get_log_channel(member.guild.id, "member_leave")
        if channel is None:
            return

        joined_at = member.joined_at
        duration_str = "Unknown"
        if joined_at:
            days = (discord.utils.utcnow() - joined_at).days
            duration_str = f"{days} days"

        await self._send_log_embed(
            channel, "📤 Member Left", member.mention,
            color=discord.Color.orange(),
            fields=[
                ("User", f"{member} ({member.id})", True),
                ("Joined", f"<t:{int(joined_at.timestamp())}:R>" if joined_at else "Unknown", True),
                ("Duration", duration_str, True),
                ("Member Count", str(member.guild.member_count), True),
                ("Roles", ", ".join(r.mention for r in member.roles[1:5]) or "*none*", False),
            ],
            thumbnail=member.display_avatar.url,
        )

    async def _on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        channel = await self._get_log_channel(member.guild.id, "voice_state")
        if channel is None:
            return

        # Joined a channel
        if before.channel is None and after.channel is not None:
            await self._send_log_embed(
                channel, "🔊 Voice Join", member.mention,
                color=discord.Color.green(),
                fields=[
                    ("User", f"{member} ({member.id})", True),
                    ("Channel", after.channel.mention, True),
                    ("Channel Type", str(after.channel.type).replace("_", " ").title(), True),
                ],
            )

        # Left a channel
        elif before.channel is not None and after.channel is None:
            duration = (discord.utils.utcnow() - member.joined_at).seconds if member.joined_at else 0
            m, sec = divmod(duration, 60)
            h, m = divmod(m, 60)
            duration_str = f"{h}h {m}m {sec}s" if h else f"{m}m {sec}s"

            await self._send_log_embed(
                channel, "🔇 Voice Leave", member.mention,
                color=discord.Color.red(),
                fields=[
                    ("User", f"{member} ({member.id})", True),
                    ("Channel", before.channel.mention, True),
                    ("Duration", duration_str, True),
                ],
            )

        # Moved between channels
        elif before.channel is not None and after.channel is not None and before.channel != after.channel:
            await self._send_log_embed(
                channel, "🔄 Voice Move", member.mention,
                color=discord.Color.blue(),
                fields=[
                    ("User", f"{member} ({member.id})", True),
                    ("From", before.channel.mention, True),
                    ("To", after.channel.mention, True),
                ],
            )
