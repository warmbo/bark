"""
Logging module v3.0.0 — uses BarkContext + EventBus.

Monitors: message edits, deletes, file uploads, member joins/leaves,
moderation actions, voice state changes.

See docs/module-workspace.md for workspace layout contract.
See docs/api-contracts.md#logging for API endpoint contracts.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, cast

import discord
from fastapi import Query, Request
from fastapi.responses import JSONResponse

from database.engine import session_scope
from database.models.attachments import FileAttachment
from modules.base import (
    BarkModule,
    CommandRegistration,
    EventRegistration,
    PageRegistration,
    PermissionDefinition,
)

logger = logging.getLogger("bark.modules.logging")

EVENT_TYPES = {
    "message_edit": "Message Edits",
    "message_delete": "Message Deletes",
    "file_upload": "File Uploads",
    "member_join": "Member Joins",
    "member_leave": "Member Leaves",
    "voice_state": "Voice State Changes",
    "automod": "AutoMod Alerts",
}


def _format_size(size_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


class LoggingModule(BarkModule):
    """Comprehensive event and file logging."""

    name = "logging"
    version = "3.0.0"
    description = "Log message edits, deletes, file uploads, member joins/leaves, voice state"
    author = "ZENHAWX"

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(name="logsetup", description="Set up logging channels"),
            CommandRegistration(name="logstatus", description="View logging configuration"),
            CommandRegistration(name="logfiles", description="Search recent file uploads"),
        ]

    def get_events(self) -> list[EventRegistration]:
        return [
            EventRegistration("discord_message", handler="_on_message"),
            EventRegistration("discord_message_edit", handler="_on_message_edit"),
            EventRegistration("discord_message_delete", handler="_on_message_delete"),
            EventRegistration("discord_member_join", handler="_on_member_join"),
            EventRegistration("discord_member_remove", handler="_on_member_remove"),
            EventRegistration("discord_voice_state", handler="_on_voice_state"),
        ]

    def get_dashboard_pages(self) -> list[PageRegistration]:
        return [
            PageRegistration(
                route="/guild/{guild_id}/modules/logging",
                label="Logging",
                icon="scroll-text",
                category="moderation",
            )
        ]

    def get_permissions(self) -> list[PermissionDefinition]:
        return [
            PermissionDefinition(name="logging.configure", label="Configure Logging"),
            PermissionDefinition(name="logging.files", label="View File Logs"),
            PermissionDefinition(name="logging.view", label="View Logs"),
        ]

    def get_about(self) -> list[dict]:
        return [
            {
                "title": "What It Does",
                "description": "Monitors message edits, deletes, file uploads, member joins/leaves, and voice state changes. Logs are posted to configurable Discord channels in real-time.",
            },
            {
                "title": "Message Tracking",
                "description": "Every edited or deleted message is logged with before/after content, author, and channel. File uploads are recorded with download links and metadata.",
            },
            {
                "title": "Join/Leave & Voice Tracking",
                "description": "Member join/leave events and voice channel activity are logged. Know when members join, leave, move between voice channels, or upload files.",
            },
            {
                "title": "Configuration",
                "description": "Use /logsetup command or the dashboard Configuration section to set per-event-type logging channels. Each event type (message_edit, message_delete, file_upload, member_join, member_leave, voice_state) can have its own channel.",
            },
        ]

    def get_settings_schema(self) -> dict:
        return {
            "type": "object",
            "description": "Configure which server events are logged and which channels they go to.",
            "properties": {
                event_type: {
                    "type": "object",
                    "title": label,
                    "description": {
                        "message_edit": "Logs when a message is edited, showing before/after content.",
                        "message_delete": "Logs when a message is deleted, including content and attachments.",
                        "file_upload": "Logs when files are uploaded with download URLs.",
                        "member_join": "Logs when a new member joins the server.",
                        "member_leave": "Logs when a member leaves or is removed.",
                        "voice_state": "Logs voice channel joins, leaves, and moves.",
                    }.get(event_type, f"Logging config for {event_type}"),
                    "properties": {
                        "channel_id": {
                            "type": "string",
                            "format": "channel_select",
                            "title": "Channel",
                            "placeholder": "Select a channel...",
                            "description": "The Discord channel where these logs will be posted.",
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

    def get_actions(self) -> list[dict]:
        # No Operate tab: log configuration lives in Configure and the Logs
        # tab is the read-only surface. (Test Log was the only action.)
        return []

    def get_extra_tabs(self) -> list[dict]:
        return [
            {
                "id": "logs",
                "label": "Logs",
                "template": "module_tabs/logging_logs.html",
            },
        ]

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        # link_posted audit dedupe: (guild, author, link) -> last-write ts so a
        # link-spam burst (or a user re-posting) does not become a write storm
        # on audit_logs. Bounded LRU.
        self._link_log: OrderedDict[tuple[int, int, str], float] = OrderedDict()
        self._link_log_max = 2048

    async def enable(self) -> None:
        self._logger.info("Enabling logging module v%s", self.version)
        # Hear AutoMod triggers from the moderation module so alerts land in
        # the guild's configured mod-log channel.
        try:
            self.ctx.events.subscribe("automod_triggered", self._on_automod_event)
        except Exception:
            self._logger.exception("Failed to subscribe to automod_triggered")

    async def disable(self) -> None:
        self._logger.info("Disabling logging module")
        try:
            self.ctx.events.unsubscribe("automod_triggered", self._on_automod_event)
        except Exception:
            self._logger.exception("Failed to unsubscribe from automod_triggered")

    async def _on_automod_event(self, event_type: str, **data) -> None:
        """Post AutoMod/raid alerts to the guild's configured mod-log channel."""
        if event_type != "automod_triggered":
            return
        guild_id = int(data.get("guild_id") or 0)
        if not guild_id:
            return
        ch = await self._get_channel(guild_id, "automod")
        if not ch:
            return
        embed = discord.Embed(
            title="🚨 AutoMod Triggered",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Rule", value=str(data.get("rule", "unknown"))[:256], inline=True)
        embed.add_field(name="Action", value=str(data.get("action", "none")), inline=True)
        embed.add_field(name="User", value=str(data.get("user_tag", "Unknown"))[:256], inline=True)
        content = data.get("content", "")
        if content:
            embed.add_field(name="Message", value=str(content)[:1024], inline=False)
        try:
            await ch.send(embed=embed)
        except discord.Forbidden:
            logger.warning("Cannot post AutoMod alert to %s (missing permissions)", ch)
        except Exception:
            logger.exception("Error posting AutoMod alert")

    # ── Command factories ─────────────────────────────

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
        @discord.app_commands.command(name="logfiles", description="Search recent file uploads")
        @discord.app_commands.default_permissions(manage_guild=True)
        async def logfiles(
            interaction: discord.Interaction,
            member: discord.Member | None = None,
            file_type: str | None = None,
            limit: int = 10,
        ):
            await self._cmd_logfiles(interaction, member, file_type, limit)

        return logfiles

    async def _cmd_logsetup(self, interaction, event_type, channel, enabled):
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)
        if event_type not in EVENT_TYPES:
            return await interaction.followup.send(
                f"Invalid. Valid: {', '.join(EVENT_TYPES.keys())}", ephemeral=True
            )
        config = await self.load_dashboard_config(interaction.guild.id)
        config[event_type] = {"channel_id": str(channel.id), "enabled": enabled}
        await self.save_dashboard_config(interaction.guild.id, config)
        await interaction.followup.send(
            f"✅ {EVENT_TYPES[event_type]} → #{channel.name}", ephemeral=True
        )

    async def _cmd_logstatus(self, interaction):
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)
        from sqlalchemy import func, select

        async with session_scope() as session:
            fc = await session.execute(
                select(func.count(FileAttachment.id)).where(
                    FileAttachment.guild_id == str(interaction.guild.id)
                )
            )
            total_files = fc.scalar() or 0
        configs = await self.load_dashboard_config(interaction.guild.id)
        if not configs:
            return await interaction.followup.send("No channels configured.", ephemeral=True)
        embed = discord.Embed(title="Logging Config", color=discord.Color.blurple())
        for event_type, config in configs.items():
            if not isinstance(config, dict):
                continue
            ch = (
                interaction.guild.get_channel(int(config["channel_id"]))
                if config.get("channel_id")
                else None
            )
            embed.add_field(
                name=f"{'✅' if config.get('enabled') else '❌'} {EVENT_TYPES.get(event_type, event_type)}",
                value=f"Channel: #{ch.name if ch else 'deleted'}",
                inline=False,
            )
        if total_files:
            embed.set_footer(text=f"{total_files} files logged")
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _cmd_logfiles(self, interaction, member, file_type, limit):
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)
        from sqlalchemy import desc, select

        query = select(FileAttachment).where(FileAttachment.guild_id == str(interaction.guild.id))
        if member:
            query = query.where(FileAttachment.author_id == str(member.id))
        if file_type:
            query = query.where(FileAttachment.content_type.like(f"{file_type}%"))
        query = query.order_by(desc(FileAttachment.created_at)).limit(min(limit, 50))
        async with session_scope() as session:
            files = (await session.execute(query)).scalars().all()
            if not files:
                return await interaction.followup.send("No files found.", ephemeral=True)
            embed = discord.Embed(title=f"Files ({len(files)})", color=discord.Color.blurple())
            for f in files:
                embed.add_field(
                    name=f"{'🖼' if f.is_image else '📄'} {f.filename}",
                    value=f"**By:** {f.author_tag}\n**Size:** {_format_size(f.file_size)}\n[Download]({f.file_url})",
                    inline=False,
                )
            await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Canonical ModuleConfig reading ─────────────────

    async def _get_channel(self, guild_id: int, event_type: str) -> discord.TextChannel | None:
        config = await self.load_dashboard_config(guild_id)
        event_config = config.get(event_type, {})
        if event_config.get("enabled") and event_config.get("channel_id"):
            guild = self.ctx.get_guild(guild_id)
            if guild:
                channel = guild.get_channel(int(event_config["channel_id"]))
                return cast(discord.TextChannel | None, channel)
        return None

    async def _send(
        self, channel, title, desc, color=discord.Color.blurple(), fields=None, thumbnail=None
    ):
        embed = discord.Embed(
            title=title, description=desc, color=color, timestamp=datetime.now(timezone.utc)
        )
        if fields:
            for n, v, i in fields:
                embed.add_field(name=n, value=v, inline=i)
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            logger.warning("Cannot send log embed to %s (missing permissions)", channel)

    # ── Event handlers ─────────────────────────────

    async def _on_message(self, event_type: str, **data):
        msg = data.get("message")
        if not msg or msg.author.bot or not msg.guild:
            return

        # Record posted links as notable activity (abnormal-feed signal).
        # Deduped per (guild, author, link) for 10 minutes — a link-spam burst
        # must not become an audit_logs write storm.
        if msg.content:
            links = re.findall(r"https?://[^\s<>]+", msg.content)
            if links:
                key = (msg.guild.id, msg.author.id, links[0])
                now_ts = time.time()
                if self._link_log.get(key, 0.0) < now_ts - 600:
                    self._link_log[key] = now_ts
                    self._link_log.move_to_end(key)
                    while len(self._link_log) > self._link_log_max:
                        self._link_log.popitem(last=False)
                    await self.ctx.log_audit(
                        msg.guild.id,
                        "link_posted",
                        str(msg.author.id),
                        actor_tag=str(msg.author),
                        target_id=str(msg.id),
                        details={
                            "channel_id": str(msg.channel.id),
                            "channel": str(msg.channel),
                            "link": links[0][:300],
                            "links": links[:5],
                        },
                    )

        if not msg.attachments:
            return
        ch = await self._get_channel(msg.guild.id, "file_upload")
        for att in msg.attachments:
            is_img = att.content_type and att.content_type.startswith("image/")
            async with session_scope() as session:
                session.add(
                    FileAttachment(
                        guild_id=str(msg.guild.id),
                        channel_id=str(msg.channel.id),
                        message_id=str(msg.id),
                        author_id=str(msg.author.id),
                        author_tag=str(msg.author),
                        filename=att.filename,
                        file_url=att.url,
                        file_size=att.size,
                        content_type=att.content_type or "application/octet-stream",
                        is_image=is_img,
                    )
                )
                await session.commit()
            if ch:
                await self._send(
                    ch,
                    f"{'🖼' if is_img else '📄'} File: {att.filename}",
                    f"in {msg.channel.mention}",
                    color=discord.Color.green(),
                    fields=[
                        ("Author", msg.author.mention, True),
                        ("Size", _format_size(att.size), True),
                    ],
                )

    async def _on_message_edit(self, event_type: str, **data):
        before, after = data.get("before"), data.get("after")
        if (
            not before
            or not after
            or before.author.bot
            or before.content == after.content
            or not before.guild
        ):
            return
        ch = await self._get_channel(before.guild.id, "message_edit")
        if not ch:
            return
        fields = [
            ("Author", before.author.mention, True),
            ("Channel", before.channel.mention, True),
        ]
        if before.content:
            fields.append(("Before", before.content[:1000], False))
        if after.content:
            fields.append(("After", after.content[:1000], False))
        await self._send(
            ch, "✏️ Edited", f"in {before.channel.mention}", discord.Color.blue(), fields
        )
        await self.ctx.log_audit(
            before.guild.id,
            "message_edit",
            str(before.author.id),
            actor_tag=str(before.author),
            target_id=str(before.id),
            details={
                "channel_id": str(before.channel.id),
                "channel": str(before.channel),
                "before": (before.content or "")[:400],
                "after": (after.content or "")[:400],
            },
        )

    async def _on_message_delete(self, event_type: str, **data):
        msg = data.get("message")
        if not msg or msg.author.bot or not msg.guild:
            return
        ch = await self._get_channel(msg.guild.id, "message_delete")
        if not ch:
            return
        fields = [("Author", msg.author.mention, True), ("Channel", msg.channel.mention, True)]
        if msg.content:
            fields.append(("Content", msg.content[:1000], False))
        if msg.attachments:
            files = "\n".join(f"[{a.filename}]({a.url})" for a in msg.attachments)
            fields.append(("Attachments", files, False))
        await self._send(ch, "🗑️ Deleted", f"in {msg.channel.mention}", discord.Color.red(), fields)
        await self.ctx.log_audit(
            msg.guild.id,
            "message_delete",
            str(msg.author.id),
            actor_tag=str(msg.author),
            target_id=str(msg.id),
            details={
                "channel_id": str(msg.channel.id),
                "channel": str(msg.channel),
                "content": (msg.content or "")[:400],
                "attachments": [a.filename for a in msg.attachments][:5],
            },
        )

    async def _on_member_join(self, event_type: str, **data):
        member = data.get("member")
        if not member:
            return
        ch = await self._get_channel(member.guild.id, "member_join")
        if not ch:
            return
        age = (discord.utils.utcnow() - member.created_at).days
        await self._send(
            ch,
            "📥 Joined",
            member.mention,
            discord.Color.green(),
            fields=[
                ("User", f"{member} ({member.id})", True),
                ("Age", f"{age}d", True),
                ("Members", str(member.guild.member_count), True),
            ],
            thumbnail=member.display_avatar.url,
        )

    async def _on_member_remove(self, event_type: str, **data):
        member = data.get("member")
        if not member:
            return
        ch = await self._get_channel(member.guild.id, "member_leave")
        if not ch:
            return
        await self._send(
            ch,
            "📤 Left",
            member.mention,
            discord.Color.orange(),
            fields=[
                ("User", f"{member} ({member.id})", True),
                ("Members", str(member.guild.member_count), True),
            ],
            thumbnail=member.display_avatar.url,
        )

    async def _on_voice_state(self, event_type: str, **data):
        member, before, after = data.get("member"), data.get("before"), data.get("after")
        if not member or not member.guild:
            return
        before_channel, after_channel = await self.ctx.normalize_voice_transition(
            member.guild.id,
            data.get("before_channel", before.channel if before else None),
            data.get("after_channel", after.channel if after else None),
        )
        if before_channel is None and after_channel is None:
            return
        ch = await self._get_channel(member.guild.id, "voice_state")
        if not ch:
            return
        if before_channel is None and after_channel is not None:
            await self._send(
                ch,
                "🔊 Voice Join",
                member.mention,
                discord.Color.green(),
                fields=[
                    ("User", f"{member} ({member.id})", True),
                    ("Channel", self._voice_channel_label(after_channel), True),
                ],
            )
        elif before_channel is not None and after_channel is None:
            await self._send(
                ch,
                "🔇 Voice Leave",
                member.mention,
                discord.Color.red(),
                fields=[
                    ("User", f"{member} ({member.id})", True),
                    ("Channel", self._voice_channel_label(before_channel), True),
                ],
            )
        elif before_channel != after_channel:
            await self._send(
                ch,
                "🔄 Voice Move",
                member.mention,
                discord.Color.blue(),
                fields=[
                    ("User", f"{member} ({member.id})", True),
                    ("From", self._voice_channel_label(before_channel), True),
                    ("To", self._voice_channel_label(after_channel), True),
                ],
            )

    @staticmethod
    def _voice_channel_label(channel) -> str:
        """Render a stable channel label for voice log embeds.

        Uses the channel's name text instead of a ``<#id>`` mention so the log
        keeps showing the name as it was even after the channel is deleted
        (Auto Voice temporary channels are removed seconds after a leave).
        """
        name = getattr(channel, "name", None)
        if name:
            return f"#{name}"
        mention = getattr(channel, "mention", None)
        return mention or "Unknown"

    # ── API Routes (module actions) ──────────────────

    def get_api_routes(self):
        """Register API endpoints for the Logging module's dashboard actions.
        Test log is handled via dashboard router at POST /modules/{module_name}/test.
        ``GET /modules/logging/logs`` returns Bark's own audit-log entries
        (message edits/deletes/links, member joins/leaves, voice state).
        """
        from fastapi import APIRouter

        from services.response import (
            api_error,
            api_not_found,
            api_success,
            check_api_permission,
            get_module_min_role,
        )

        router = APIRouter(tags=["module-logging"])

        @router.get("/guilds/{guild_id}/modules/logging/logs")
        async def list_logs(
            request: Request,
            guild_id: str,
            limit: int = Query(50, ge=1, le=200),
        ):
            """Return recent audit-log entries recorded for this guild."""
            await get_module_min_role("logging", guild_id)
            if not check_api_permission(request, "logging.view", guild_id):
                return api_error("Insufficient permissions", status_code=403)
            gid = int(guild_id)
            bot = request.state.bot
            guild = bot.get_guild(gid)
            if guild is None:
                return api_not_found("Guild")

            from sqlalchemy import desc, select

            from database.models.moderation import AuditLog

            async with session_scope() as session:
                result = await session.execute(
                    select(AuditLog)
                    .where(AuditLog.guild_id == str(gid))
                    .order_by(desc(AuditLog.created_at))
                    .limit(min(limit, 200))
                )
                rows = list(result.scalars().all())

            def member_name(user_id: str | None, fallback: str | None = None) -> str:
                if user_id:
                    try:
                        member = guild.get_member(int(user_id))
                    except (TypeError, ValueError):
                        member = None
                    if member is not None:
                        return str(getattr(member, "display_name", None) or member)
                return fallback or user_id or "Unknown"

            entries = []
            for row in rows:
                details: dict[str, Any] = {}
                try:
                    details = json.loads(row.details) if row.details else {}
                except (json.JSONDecodeError, TypeError):
                    details = {}
                actor = member_name(row.actor_id, details.get("actor_tag"))
                target = member_name(row.target_id, details.get("target_tag"))
                channel = details.get("channel") or ""
                entries.append(
                    {
                        "id": row.id,
                        "action": row.action,
                        "actor_id": row.actor_id,
                        "actor": actor,
                        "target_id": row.target_id,
                        "target": target,
                        "channel": channel,
                        "details": details,
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                    }
                )

            return api_success({"entries": entries, "total": len(entries)})

        @router.get("/guilds/{guild_id}/modules/logging/logs/export")
        async def export_logs(request: Request, guild_id: str, limit: int = Query(1000, ge=1, le=5000)):
            """Download audit-log entries for this guild as CSV.

            Same permission gate as list_logs; the download button on the
            Logs tab hits this with an Accept: text/csv header and the
            browser saves the attachment.
            """
            await get_module_min_role("logging", guild_id)
            if not check_api_permission(request, "logging.view", guild_id):
                return api_error("Insufficient permissions", status_code=403)
            gid = int(guild_id)
            bot = request.state.bot
            guild = bot.get_guild(gid)
            if guild is None:
                return api_not_found("Guild")

            from sqlalchemy import desc, select

            from database.models.moderation import AuditLog

            async with session_scope() as session:
                result = await session.execute(
                    select(AuditLog)
                    .where(AuditLog.guild_id == str(gid))
                    .order_by(desc(AuditLog.created_at))
                    .limit(min(limit, 5000))
                )
                rows = list(result.scalars().all())

            def member_name(user_id: str | None, fallback: str | None = None) -> str:
                if user_id:
                    try:
                        member = guild.get_member(int(user_id))
                    except (TypeError, ValueError):
                        member = None
                    if member is not None:
                        return str(getattr(member, "display_name", None) or member)
                return fallback or user_id or "Unknown"

            import csv
            import io

            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["id", "action", "actor_id", "actor", "target_id", "target", "channel", "details", "created_at"])
            for row in rows:
                details: dict[str, Any] = {}
                try:
                    details = json.loads(row.details) if row.details else {}
                except (json.JSONDecodeError, TypeError):
                    details = {}
                writer.writerow(
                    [
                        row.id,
                        row.action,
                        row.actor_id or "",
                        member_name(row.actor_id, details.get("actor_tag")),
                        row.target_id or "",
                        member_name(row.target_id, details.get("target_tag")),
                        details.get("channel") or "",
                        json.dumps(details, ensure_ascii=False),
                        row.created_at.isoformat() if row.created_at else "",
                    ]
                )

            from fastapi.responses import Response

            return Response(
                content=buffer.getvalue(),
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="bark-logs-{guild_id}.csv"',
                },
            )

        return router

    async def _handle_test_action(self, guild_id: str) -> JSONResponse:
        """Send a test embed to each configured log channel. Used by dashboard route."""
        guild_id_int = int(guild_id)
        from services.response import api_error, api_success

        sent = 0
        errors = 0
        for event_type, label in EVENT_TYPES.items():
            ch = await self._get_channel(guild_id_int, event_type)
            if ch is None:
                continue
            try:
                embed = discord.Embed(
                    title=f"🧪 Test — {label}",
                    description="If you can see this, logging is configured correctly.",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc),
                )
                embed.set_footer(text="Bark Logging Module")
                await ch.send(embed=embed)
                sent += 1
            except Exception:
                errors += 1

        if sent == 0:
            return api_error(
                "No logging channels configured. Set up channels in the Configuration section first.",
                status_code=400,
            )
        msg = f"Sent test messages to {sent} channel(s)"
        if errors:
            msg += f" ({errors} failed)"
        return api_success({"message": msg, "sent": sent, "errors": errors})
