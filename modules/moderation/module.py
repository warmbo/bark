"""
Moderation module for Bark v2.0.

Provides: warn, timeout, kick, ban, unban, voice control, full case tracking.
Every action creates a detailed audit log entry.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
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
from database.models.moderation import ModerationCase, Warning, AuditLog
from database.models.voice import VoiceSession

if TYPE_CHECKING:
    from bot.client import BarkBot

logger = logging.getLogger("bark.modules.moderation")


class ModerationModule(BarkModule):
    """Server moderation with full case tracking and voice controls."""

    name = "moderation"
    version = "2.0.0"
    description = (
        "Warn, timeout, kick, ban, unban, and voice-control members "
        "with full case tracking and audit logging"
    )
    author = "ZENHAWX"

    def __init__(self, bot: BarkBot) -> None:
        super().__init__(bot)

    # ── Registration ──────────────────────────────────

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(name="warn", description="Warn a member"),
            CommandRegistration(name="timeout", description="Timeout a member"),
            CommandRegistration(name="kick", description="Kick a member"),
            CommandRegistration(name="ban", description="Ban a member"),
            CommandRegistration(name="unban", description="Unban a member"),
            CommandRegistration(name="cases", description="View moderation cases"),
            CommandRegistration(name="warnings", description="View member warnings"),
            CommandRegistration(name="clearwarn", description="Clear a warning"),
            CommandRegistration(name="vc_kick", description="Disconnect a member from voice"),
            CommandRegistration(name="vc_move", description="Move a member to another voice channel"),
            CommandRegistration(name="vc_mute", description="Server-mute a member in voice"),
            CommandRegistration(name="vc_unmute", description="Server-unmute a member in voice"),
            CommandRegistration(name="vc_deafen", description="Server-deafen a member in voice"),
            CommandRegistration(name="vc_undeafen", description="Server-undeafen a member in voice"),
            CommandRegistration(name="voice_sessions", description="View voice session history for a member"),
        ]

    def get_events(self) -> list[EventRegistration]:
        return [
            EventRegistration(event_name="on_voice_state_update"),
        ]

    def get_dashboard_pages(self) -> list[PageRegistration]:
        return [
            PageRegistration(
                route="/guild/{guild_id}/moderation",
                label="Moderation",
                icon="⚖",
            ),
        ]

    def get_permissions(self) -> list[PermissionDefinition]:
        return [
            PermissionDefinition(name="moderation.warn", label="Warn Members", description="Issue warnings"),
            PermissionDefinition(name="moderation.timeout", label="Timeout Members", description="Timeout members"),
            PermissionDefinition(name="moderation.kick", label="Kick Members", description="Kick members"),
            PermissionDefinition(name="moderation.ban", label="Ban Members", description="Ban members"),
            PermissionDefinition(name="moderation.unban", label="Unban Members", description="Unban members"),
            PermissionDefinition(name="moderation.vc_kick", label="Voice Kick", description="Disconnect members from voice"),
            PermissionDefinition(name="moderation.vc_move", label="Voice Move", description="Move members between voice channels"),
            PermissionDefinition(name="moderation.vc_mute", label="Voice Mute", description="Server-mute members"),
            PermissionDefinition(name="moderation.cases", label="View Cases", description="View moderation cases"),
        ]

    # ── Lifecycle ─────────────────────────────────────

    async def enable(self) -> None:
        self._logger.info("Enabling moderation module v%s", self.version)
        try:
            if hasattr(self.bot, "tree"):
                for name in ("warn", "timeout", "kick", "ban", "unban", "cases",
                             "warnings", "clearwarn", "vc_kick", "vc_move",
                             "vc_mute", "vc_unmute", "vc_deafen", "vc_undeafen",
                             "voice_sessions"):
                    self.bot.tree.add_command(getattr(self, f"_make_{name}_command")())
            self.bot.add_listener(self._on_voice_state_update, "on_voice_state_update")
        except Exception:
            self._logger.exception("Failed to enable moderation module")
            raise

    async def disable(self) -> None:
        self._logger.info("Disabling moderation module")
        try:
            if hasattr(self.bot, "tree"):
                for name in ("warn", "timeout", "kick", "ban", "unban", "cases",
                             "warnings", "clearwarn", "vc_kick", "vc_move",
                             "vc_mute", "vc_unmute", "vc_deafen", "vc_undeafen",
                             "voice_sessions"):
                    self.bot.tree.remove_command(name)
        except Exception:
            self._logger.exception("Failed to disable moderation module")

    # ── Text Command Factories ────────────────────────

    def _make_warn_command(self):
        @discord.app_commands.command(name="warn", description="Warn a member")
        @discord.app_commands.default_permissions(moderate_members=True)
        async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
            await self._cmd_warn(interaction, member, reason)
        return warn

    def _make_timeout_command(self):
        @discord.app_commands.command(name="timeout", description="Timeout a member")
        @discord.app_commands.default_permissions(moderate_members=True)
        async def timeout(
            interaction: discord.Interaction,
            member: discord.Member,
            duration: int,
            unit: str = "minutes",
            reason: str = "No reason provided",
        ):
            await self._cmd_timeout(interaction, member, duration, unit, reason)
        return timeout

    def _make_kick_command(self):
        @discord.app_commands.command(name="kick", description="Kick a member")
        @discord.app_commands.default_permissions(kick_members=True)
        async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
            await self._cmd_kick(interaction, member, reason)
        return kick

    def _make_ban_command(self):
        @discord.app_commands.command(name="ban", description="Ban a member")
        @discord.app_commands.default_permissions(ban_members=True)
        async def ban(
            interaction: discord.Interaction,
            member: discord.Member,
            reason: str = "No reason provided",
            delete_days: int = 0,
        ):
            await self._cmd_ban(interaction, member, reason, delete_days)
        return ban

    def _make_unban_command(self):
        @discord.app_commands.command(name="unban", description="Unban a user")
        @discord.app_commands.default_permissions(ban_members=True)
        async def unban(interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
            await self._cmd_unban(interaction, user_id, reason)
        return unban

    def _make_cases_command(self):
        @discord.app_commands.command(name="cases", description="View recent moderation cases")
        async def cases(interaction: discord.Interaction, limit: int = 10):
            await self._cmd_cases(interaction, limit)
        return cases

    def _make_warnings_command(self):
        @discord.app_commands.command(name="warnings", description="View warnings for a member")
        async def warnings(interaction: discord.Interaction, member: discord.Member):
            await self._cmd_warnings(interaction, member)
        return warnings

    def _make_clearwarn_command(self):
        @discord.app_commands.command(name="clearwarn", description="Clear a warning by ID")
        @discord.app_commands.default_permissions(moderate_members=True)
        async def clearwarn(interaction: discord.Interaction, warning_id: int):
            await self._cmd_clearwarn(interaction, warning_id)
        return clearwarn

    def _make_voice_sessions_command(self):
        @discord.app_commands.command(name="voice_sessions", description="View voice session history for a member")
        @discord.app_commands.default_permissions(moderate_members=True)
        async def voice_sessions(interaction: discord.Interaction, member: discord.Member, limit: int = 5):
            await self._cmd_voice_sessions(interaction, member, limit)
        return voice_sessions

    # ── Voice Command Factories ───────────────────────

    def _make_vc_kick_command(self):
        @discord.app_commands.command(name="vc_kick", description="Disconnect a member from voice")
        @discord.app_commands.default_permissions(mute_members=True)
        async def vc_kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
            await self._cmd_vc_kick(interaction, member, reason)
        return vc_kick

    def _make_vc_move_command(self):
        @discord.app_commands.command(name="vc_move", description="Move a member to another voice channel")
        @discord.app_commands.default_permissions(move_members=True)
        async def vc_move(
            interaction: discord.Interaction,
            member: discord.Member,
            channel: discord.VoiceChannel,
            reason: str = "No reason provided",
        ):
            await self._cmd_vc_move(interaction, member, channel, reason)
        return vc_move

    def _make_vc_mute_command(self):
        @discord.app_commands.command(name="vc_mute", description="Server-mute a member in voice")
        @discord.app_commands.default_permissions(mute_members=True)
        async def vc_mute(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
            await self._cmd_vc_mute(interaction, member, reason)
        return vc_mute

    def _make_vc_unmute_command(self):
        @discord.app_commands.command(name="vc_unmute", description="Server-unmute a member in voice")
        @discord.app_commands.default_permissions(mute_members=True)
        async def vc_unmute(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
            await self._cmd_vc_unmute(interaction, member, reason)
        return vc_unmute

    def _make_vc_deafen_command(self):
        @discord.app_commands.command(name="vc_deafen", description="Server-deafen a member in voice")
        @discord.app_commands.default_permissions(deafen_members=True)
        async def vc_deafen(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
            await self._cmd_vc_deafen(interaction, member, reason)
        return vc_deafen

    def _make_vc_undeafen_command(self):
        @discord.app_commands.command(name="vc_undeafen", description="Server-undeafen a member in voice")
        @discord.app_commands.default_permissions(deafen_members=True)
        async def vc_undeafen(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
            await self._cmd_vc_undeafen(interaction, member, reason)
        return vc_undeafen

    # ── Text Command Handlers ─────────────────────────

    async def _cmd_warn(self, interaction: discord.Interaction, member: discord.Member, reason: str) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)

        case_number = await self._create_case(
            guild_id=interaction.guild.id,
            action_type="warn",
            target_id=str(member.id),
            target_tag=str(member),
            moderator_id=str(interaction.user.id),
            moderator_tag=str(interaction.user),
            reason=reason,
        )

        async with session_scope() as session:
            warning = Warning(
                guild_id=interaction.guild.id,
                user_id=str(member.id),
                moderator_id=str(interaction.user.id),
                reason=reason,
                active=True,
            )
            session.add(warning)
            await session.commit()

        await self._log_audit(
            guild_id=interaction.guild.id,
            action="warn",
            actor_id=str(interaction.user.id),
            actor_tag=str(interaction.user),
            target_id=str(member.id),
            target_tag=str(member),
            details={"reason": reason, "case": case_number},
        )

        await interaction.followup.send(
            f"✅ Warned {member.mention} | Case #{case_number}\nReason: {reason}"
        )

        try:
            await member.send(
                f"You have been warned in **{interaction.guild.name}**.\n"
                f"Reason: {reason}\nCase #{case_number}"
            )
        except discord.Forbidden:
            pass

    async def _cmd_timeout(
        self, interaction: discord.Interaction, member: discord.Member,
        duration: int, unit: str, reason: str,
    ) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild.me.guild_permissions.moderate_members:
            await interaction.followup.send("❌ I don't have permission to timeout members.", ephemeral=True)
            return

        unit_map = {"seconds": 1, "minutes": 60, "hours": 3600}
        seconds = duration * unit_map.get(unit, 60)
        until = discord.utils.utcnow() + timedelta(seconds=seconds)
        minutes = seconds // 60
        expiry_ts = int(until.timestamp())

        case_number = await self._create_case(
            guild_id=interaction.guild.id,
            action_type="timeout",
            target_id=str(member.id),
            target_tag=str(member),
            moderator_id=str(interaction.user.id),
            moderator_tag=str(interaction.user),
            reason=reason,
            duration=minutes,
        )

        try:
            await member.timeout(until, reason=f"Case #{case_number}: {reason}")
            await interaction.followup.send(
                f"⏱ {member.mention} timed out for {duration} {unit} | Case #{case_number}\n"
                f"Expires: <t:{expiry_ts}:R>"
            )

            await self._log_audit(
                guild_id=interaction.guild.id,
                action="timeout",
                actor_id=str(interaction.user.id),
                actor_tag=str(interaction.user),
                target_id=str(member.id),
                target_tag=str(member),
                details={
                    "duration": minutes,
                    "duration_unit": "minutes",
                    "reason": reason,
                    "case": case_number,
                    "expires_at": until.isoformat(),
                },
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ I cannot timeout that member.", ephemeral=True)

    async def _cmd_kick(self, interaction: discord.Interaction, member: discord.Member, reason: str) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild.me.guild_permissions.kick_members:
            await interaction.followup.send("❌ I don't have permission to kick members.", ephemeral=True)
            return

        case_number = await self._create_case(
            guild_id=interaction.guild.id,
            action_type="kick",
            target_id=str(member.id),
            target_tag=str(member),
            moderator_id=str(interaction.user.id),
            moderator_tag=str(interaction.user),
            reason=reason,
        )

        try:
            await member.kick(reason=f"Case #{case_number}: {reason}")
            await interaction.followup.send(
                f"👢 Kicked {member.mention} | Case #{case_number}\nReason: {reason}"
            )

            await self._log_audit(
                guild_id=interaction.guild.id,
                action="kick",
                actor_id=str(interaction.user.id),
                actor_tag=str(interaction.user),
                target_id=str(member.id),
                target_tag=str(member),
                details={"reason": reason, "case": case_number},
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ I cannot kick that member.", ephemeral=True)

    async def _cmd_ban(
        self, interaction: discord.Interaction,
        member: discord.Member, reason: str, delete_days: int,
    ) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild.me.guild_permissions.ban_members:
            await interaction.followup.send("❌ I don't have permission to ban members.", ephemeral=True)
            return

        case_number = await self._create_case(
            guild_id=interaction.guild.id,
            action_type="ban",
            target_id=str(member.id),
            target_tag=str(member),
            moderator_id=str(interaction.user.id),
            moderator_tag=str(interaction.user),
            reason=reason,
        )

        try:
            await member.ban(
                reason=f"Case #{case_number}: {reason}",
                delete_message_days=delete_days,
            )
            await interaction.followup.send(
                f"🔨 Banned {member.mention} | Case #{case_number}\nReason: {reason}"
            )

            await self._log_audit(
                guild_id=interaction.guild.id,
                action="ban",
                actor_id=str(interaction.user.id),
                actor_tag=str(interaction.user),
                target_id=str(member.id),
                target_tag=str(member),
                details={"reason": reason, "case": case_number, "delete_days": delete_days},
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ I cannot ban that member.", ephemeral=True)

    async def _cmd_unban(self, interaction: discord.Interaction, user_id: str, reason: str) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild.me.guild_permissions.ban_members:
            await interaction.followup.send("❌ I don't have permission to unban.", ephemeral=True)
            return

        try:
            user = await self.bot.fetch_user(int(user_id))
            await interaction.guild.unban(user, reason=reason)

            case_number = await self._create_case(
                guild_id=interaction.guild.id,
                action_type="unban",
                target_id=user_id,
                target_tag=str(user),
                moderator_id=str(interaction.user.id),
                moderator_tag=str(interaction.user),
                reason=reason,
            )

            await interaction.followup.send(
                f"✅ Unbanned {user.mention if user else user_id} | Case #{case_number}"
            )

            await self._log_audit(
                guild_id=interaction.guild.id,
                action="unban",
                actor_id=str(interaction.user.id),
                actor_tag=str(interaction.user),
                target_id=user_id,
                target_tag=str(user),
                details={"reason": reason, "case": case_number},
            )
        except discord.NotFound:
            await interaction.followup.send("❌ User not found or already unbanned.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ I don't have permission to unban.", ephemeral=True)

    async def _cmd_cases(self, interaction: discord.Interaction, limit: int) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)

        from sqlalchemy import select, desc

        async with session_scope() as session:
            result = await session.execute(
                select(ModerationCase)
                .where(ModerationCase.guild_id == interaction.guild.id)
                .order_by(desc(ModerationCase.created_at))
                .limit(min(limit, 50))
            )
            cases = result.scalars().all()

            if not cases:
                await interaction.followup.send("No moderation cases found.", ephemeral=True)
                return

            embed = discord.Embed(
                title=f"Recent Cases ({len(cases)})",
                color=discord.Color.blurple(),
            )
            for case in cases[:10]:
                embed.add_field(
                    name=f"#{case.case_number} — {case.action_type.upper()}",
                    value=(
                        f"**Target:** {case.target_tag}\n"
                        f"**Mod:** {case.moderator_tag}\n"
                        f"**Reason:** {case.reason or 'No reason'}\n"
                        f"**Date:** <t:{int(case.created_at.timestamp())}:R>"
                    ),
                    inline=False,
                )
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _cmd_warnings(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)

        from sqlalchemy import select, desc

        async with session_scope() as session:
            result = await session.execute(
                select(Warning)
                .where(
                    Warning.guild_id == interaction.guild.id,
                    Warning.user_id == str(member.id),
                    Warning.active == True,
                )
                .order_by(desc(Warning.created_at))
            )
            warnings = result.scalars().all()

            if not warnings:
                await interaction.followup.send(
                    f"{member.mention} has no active warnings.", ephemeral=True
                )
                return

            embed = discord.Embed(
                title=f"Warnings for {member.display_name}",
                color=discord.Color.gold(),
            )
            embed.set_thumbnail(url=member.display_avatar.url)

            for w in warnings:
                embed.add_field(
                    name=f"Warning #{w.id}",
                    value=(
                        f"**Reason:** {w.reason}\n"
                        f"**By:** <@{w.moderator_id}>\n"
                        f"**Date:** <t:{int(w.created_at.timestamp())}:R>"
                    ),
                    inline=False,
                )
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _cmd_clearwarn(self, interaction: discord.Interaction, warning_id: int) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)

        from sqlalchemy import select

        async with session_scope() as session:
            result = await session.execute(
                select(Warning).where(
                    Warning.id == warning_id,
                    Warning.guild_id == interaction.guild.id,
                )
            )
            warning = result.scalar_one_or_none()
            if warning is None:
                await interaction.followup.send("❌ Warning not found.", ephemeral=True)
                return
            warning.active = False
            await session.commit()

        await self._log_audit(
            guild_id=interaction.guild.id,
            action="clear_warning",
            actor_id=str(interaction.user.id),
            actor_tag=str(interaction.user),
            target_id=warning.user_id,
            details={"warning_id": warning_id, "original_reason": warning.reason},
        )

        await interaction.followup.send(f"✅ Warning #{warning_id} cleared.", ephemeral=True)

    async def _cmd_voice_sessions(
        self, interaction: discord.Interaction, member: discord.Member, limit: int
    ) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)

        from sqlalchemy import select, desc

        async with session_scope() as session:
            result = await session.execute(
                select(VoiceSession)
                .where(
                    VoiceSession.guild_id == interaction.guild.id,
                    VoiceSession.user_id == str(member.id),
                )
                .order_by(desc(VoiceSession.joined_at))
                .limit(min(limit, 20))
            )
            sessions = result.scalars().all()

            if not sessions:
                await interaction.followup.send(
                    f"No voice sessions recorded for {member.mention}.", ephemeral=True
                )
                return

            embed = discord.Embed(
                title=f"Voice Sessions — {member.display_name}",
                color=discord.Color.blurple(),
            )
            for s in sessions:
                duration = ""
                if s.duration_seconds is not None:
                    m, sec = divmod(s.duration_seconds, 60)
                    h, m = divmod(m, 60)
                    duration = f" ({h}h {m}m {sec}s)" if h else f" ({m}m {sec}s)"

                left = f"<t:{int(s.left_at.timestamp())}:R>" if s.left_at else "Still connected"
                embed.add_field(
                    name=f"#{s.channel_name}",
                    value=(
                        f"**Joined:** <t:{int(s.joined_at.timestamp())}:R>\n"
                        f"**Left:** {left}{duration}"
                    ),
                    inline=False,
                )
            await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Voice Command Handlers ────────────────────────

    async def _cmd_vc_kick(
        self, interaction: discord.Interaction, member: discord.Member, reason: str
    ) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)

        if member.voice is None or member.voice.channel is None:
            await interaction.followup.send("❌ That member is not in a voice channel.", ephemeral=True)
            return

        channel_name = member.voice.channel.name
        try:
            await member.move_to(None, reason=f"VC kick by {interaction.user}: {reason}")
            await interaction.followup.send(
                f"🔊 Disconnected {member.mention} from #{channel_name} | Reason: {reason}"
            )

            await self._log_audit(
                guild_id=interaction.guild.id,
                action="vc_kick",
                actor_id=str(interaction.user.id),
                actor_tag=str(interaction.user),
                target_id=str(member.id),
                target_tag=str(member),
                details={"channel": channel_name, "reason": reason},
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ I cannot disconnect that member.", ephemeral=True)

    async def _cmd_vc_move(
        self, interaction: discord.Interaction, member: discord.Member,
        channel: discord.VoiceChannel, reason: str,
    ) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)

        if member.voice is None or member.voice.channel is None:
            await interaction.followup.send("❌ That member is not in a voice channel.", ephemeral=True)
            return

        old_channel = member.voice.channel.name
        try:
            await member.move_to(channel, reason=f"VC move by {interaction.user}: {reason}")
            await interaction.followup.send(
                f"🔊 Moved {member.mention} from #{old_channel} to #{channel.name} | Reason: {reason}"
            )

            await self._log_audit(
                guild_id=interaction.guild.id,
                action="vc_move",
                actor_id=str(interaction.user.id),
                actor_tag=str(interaction.user),
                target_id=str(member.id),
                target_tag=str(member),
                details={"from_channel": old_channel, "to_channel": channel.name, "reason": reason},
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ I cannot move that member.", ephemeral=True)

    async def _cmd_vc_mute(
        self, interaction: discord.Interaction, member: discord.Member, reason: str
    ) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await member.edit(mute=True, reason=f"VC mute by {interaction.user}: {reason}")
            await interaction.followup.send(f"🔇 Server-muted {member.mention} | Reason: {reason}")
            await self._log_audit(
                guild_id=interaction.guild.id, action="vc_mute",
                actor_id=str(interaction.user.id), actor_tag=str(interaction.user),
                target_id=str(member.id), target_tag=str(member),
                details={"reason": reason},
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ I cannot mute that member.", ephemeral=True)

    async def _cmd_vc_unmute(
        self, interaction: discord.Interaction, member: discord.Member, reason: str
    ) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await member.edit(mute=False, reason=f"VC unmute by {interaction.user}: {reason}")
            await interaction.followup.send(f"🔊 Server-unmuted {member.mention} | Reason: {reason}")
            await self._log_audit(
                guild_id=interaction.guild.id, action="vc_unmute",
                actor_id=str(interaction.user.id), actor_tag=str(interaction.user),
                target_id=str(member.id), target_tag=str(member),
                details={"reason": reason},
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ I cannot unmute that member.", ephemeral=True)

    async def _cmd_vc_deafen(
        self, interaction: discord.Interaction, member: discord.Member, reason: str
    ) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await member.edit(deafen=True, reason=f"VC deafen by {interaction.user}: {reason}")
            await interaction.followup.send(f"🔇 Server-deafened {member.mention} | Reason: {reason}")
            await self._log_audit(
                guild_id=interaction.guild.id, action="vc_deafen",
                actor_id=str(interaction.user.id), actor_tag=str(interaction.user),
                target_id=str(member.id), target_tag=str(member),
                details={"reason": reason},
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ I cannot deafen that member.", ephemeral=True)

    async def _cmd_vc_undeafen(
        self, interaction: discord.Interaction, member: discord.Member, reason: str
    ) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await member.edit(deafen=False, reason=f"VC undeafen by {interaction.user}: {reason}")
            await interaction.followup.send(f"🔊 Server-undeafened {member.mention} | Reason: {reason}")
            await self._log_audit(
                guild_id=interaction.guild.id, action="vc_undeafen",
                actor_id=str(interaction.user.id), actor_tag=str(interaction.user),
                target_id=str(member.id), target_tag=str(member),
                details={"reason": reason},
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ I cannot undeafen that member.", ephemeral=True)

    # ── Voice State Tracking ──────────────────────────

    async def _on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Track voice session start/end times in the database."""
        if not member.guild:
            return

        guild_id = member.guild.id
        user_id = str(member.id)
        now = datetime.now(timezone.utc)

        # Joined a channel
        if before.channel is None and after.channel is not None:
            async with session_scope() as session:
                session.add(VoiceSession(
                    guild_id=guild_id,
                    user_id=user_id,
                    user_tag=str(member),
                    channel_id=str(after.channel.id),
                    channel_name=after.channel.name,
                    joined_at=now,
                ))
                await session.commit()

        # Left a channel — close the open session
        elif before.channel is not None and after.channel is None:
            from sqlalchemy import select, desc

            async with session_scope() as session:
                result = await session.execute(
                    select(VoiceSession)
                    .where(
                        VoiceSession.guild_id == guild_id,
                        VoiceSession.user_id == user_id,
                        VoiceSession.channel_id == str(before.channel.id),
                        VoiceSession.left_at.is_(None),
                    )
                    .order_by(desc(VoiceSession.joined_at))
                    .limit(1)
                )
                session_record = result.scalar_one_or_none()
                if session_record:
                    session_record.left_at = now
                    session_record.duration_seconds = int((now - session_record.joined_at).total_seconds())
                    await session.commit()

    # ── Helpers ───────────────────────────────────────

    async def _create_case(
        self,
        guild_id: int,
        action_type: str,
        target_id: str,
        target_tag: str,
        moderator_id: str,
        moderator_tag: str,
        reason: str,
        duration: int | None = None,
    ) -> int:
        from sqlalchemy import select, func

        async with session_scope() as session:
            result = await session.execute(
                select(func.coalesce(func.max(ModerationCase.case_number), 0) + 1)
                .where(ModerationCase.guild_id == guild_id)
            )
            case_number = result.scalar()

            case = ModerationCase(
                guild_id=guild_id,
                case_number=case_number,
                action_type=action_type,
                target_id=target_id,
                target_tag=target_tag,
                moderator_id=moderator_id,
                moderator_tag=moderator_tag,
                reason=reason,
                duration=duration,
            )
            session.add(case)
            await session.commit()

        return case_number

    async def _log_audit(
        self,
        guild_id: int,
        action: str,
        actor_id: str,
        actor_tag: str = "",
        target_id: str | None = None,
        target_tag: str = "",
        details: dict | None = None,
    ) -> None:
        import json

        async with session_scope() as session:
            log = AuditLog(
                guild_id=guild_id,
                action=action,
                actor_id=actor_id,
                target_id=target_id,
                details=json.dumps({
                    "actor_tag": actor_tag,
                    "target_tag": target_tag,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **(details or {}),
                }),
            )
            session.add(log)
            await session.commit()
