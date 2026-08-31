"""Help module — `bark!help` DMs every available text command.

Walks the live prefix-command table (the exact commands the bot accepts after
its configured prefix), builds a command reference embed, and DMs it to the
invoker along with dashboard / invite access info. Falls back to an ephemeral
in-channel copy when the user has DMs disabled.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord

from config import config
from modules.base import BarkModule, CommandRegistration

logger = logging.getLogger("bark.help")


def _walk_commands(command, prefix: str, path: list[str], out: list[tuple[str, str]]) -> None:
    """Collect (full path, description) for every leaf prefix command."""
    subs = getattr(command, "commands", None)
    if subs:  # a group (e.g. bark!trivia start)
        items = subs.values() if isinstance(subs, dict) else subs
        for sub in items:
            _walk_commands(sub, prefix, path + [sub.name], out)
    else:
        out.append((f"{prefix}{' '.join(path)}", command.description or ""))


class HelpModule(BarkModule):
    name = "help"
    version = "1.0.0"
    description = "DMs every available text command plus dashboard info."

    async def _prefix(self, guild_id=None) -> str:
        """The slash invocation prefix, e.g. ``/bark `` (slash commands are the
        interface now). Returns a trailing-space string so paths read
        ``/bark warn``, ``/bark trivia start``.
        """
        return f"/{self._group_name()} "

    def _group_name(self) -> str:
        try:
            return self.ctx.bot.modules.command_group_name()
        except Exception:
            return config.bot.command_group or "bark"

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(
                name="help",
                description="Send a DM with every text command and dashboard info",
            ),
            CommandRegistration(
                name="info",
                description="Show server stats: members, channels, roles, boosts, age",
            ),
            CommandRegistration(
                name="stats",
                description="Show server activity stats: top channels, games, rep, voice, and more",
            ),
        ]

    def _make_help_command(self):
        @discord.app_commands.command(
            name="help",
            description="Send a DM with every text command and dashboard info",
        )
        async def help_cmd(interaction: discord.Interaction):
            prefix = await self._prefix(
                interaction.guild.id if interaction.guild is not None else None
            )
            commands: list[tuple[str, str]] = []
            bot = self.ctx.bot
            # discord.ext.commands.Bot.commands is a SET of Command objects
            # (not a dict) — handle both shapes defensively.
            raw = getattr(bot, "commands", ()) or ()
            iterable = list(raw.values()) if isinstance(raw, dict) else list(raw)
            for cmd in iterable:
                _walk_commands(cmd, prefix, [cmd.name], commands)
            commands.sort(key=lambda item: item[0])

            public_url = getattr(config.dashboard, "public_url", "")
            instructions = discord.Embed(
                title="🐺 How to use Bark",
                description=(
                    "Bark is a dashboard-first server manager: you run it from "
                    "this dashboard, and command it from Discord with text "
                    "commands. Here's the quick tour:"
                ),
                color=discord.Color.blurple(),
            )
            instructions.add_field(
                name="1. Add Bark to a server",
                value=(
                    "Use the invite link below to install Bark in any server "
                    "you manage. It needs **Manage Server** permissions."
                ),
                inline=False,
            )
            instructions.add_field(
                name="2. Enable the modules you want",
                value=(
                    "Each server has its own **Modules** page in the dashboard. "
                    "Core modules (moderation, reputation, roles, logging…) are "
                    "on by default; **add-on plugins are off until you turn "
                    "them on for that server**."
                ),
                inline=False,
            )
            instructions.add_field(
                name="3. Configure per server",
                value=(
                    "Open a server, then its module pages to set channels, "
                    "roles, and rules. Instance-wide things — updates, backups, "
                    "dashboard access, bot appearance — live in **Settings**."
                ),
                inline=False,
            )
            instructions.add_field(
                name=f"4. Use {prefix}commands in Discord",
                value=(
                    f"Type `{prefix}help` (this DM), `{prefix}warn`, "
                    f"`{prefix}announce`, `{prefix}serverinfo`… Type `/` then "
                    f"`{self._group_name()}` and pick a command from the "
                    "autocomplete list."
                ),
                inline=False,
            )
            instructions.add_field(
                name="5. Add features & keep it fresh",
                value=(
                    "Install single-file add-ons from **Modules → Plugin "
                    "Manager**, and update Bark from **Settings → Updates** "
                    "(with an automatic database backup first)."
                ),
                inline=False,
            )
            if public_url:
                instructions.add_field(
                    name="Links",
                    value=(f"**Dashboard:** {public_url}\n**Invite:** {public_url}/invite"),
                    inline=False,
                )
            instructions.set_footer(text=f"Bark {self.name} v{self.version}")

            reference = discord.Embed(
                title="🐺 Bark — Command Reference",
                color=discord.Color.blurple(),
            )
            if commands:
                reference.description = "\n".join(
                    f"`{path}`{' — ' + desc if desc else ''}" for path, desc in commands
                )
            else:
                reference.description = "No commands registered yet."
            if public_url:
                reference.add_field(
                    name="Manage Bark",
                    value=f"**Dashboard:** {public_url}\n**Invite:** {public_url}/invite",
                    inline=False,
                )
            reference.add_field(
                name="Tip",
                value=(
                    f"Run `{prefix}help` anytime — the bot DMs you this list. "
                    "Text commands (`bark!…`) reply in the channel; only `help` "
                    "uses DMs. Slash info commands stay private unless you add "
                    "`public` as the last argument."
                ),
                inline=False,
            )
            reference.set_footer(text=f"Bark {self.name} v{self.version}")

            # Interactive: a select menu on the reference DM lets the user run
            # any command straight from the picker.
            picker = None
            dispatcher = getattr(getattr(self.ctx.bot, "modules", None), "_dispatcher", None)
            if dispatcher is not None:
                from services.interactions import attach_command_picker

                picker = attach_command_picker(dispatcher)

            try:
                await interaction.user.send(embed=instructions)
                if picker is not None:
                    await interaction.user.send(embed=reference, view=picker)
                else:
                    await interaction.user.send(embed=reference)
            except discord.Forbidden:
                await interaction.response.send_message(
                    "I couldn't DM you (DMs from server members may be off). "
                    "Here's the command list instead:",
                    ephemeral=True,
                )
                try:
                    await interaction.followup.send(embed=instructions, ephemeral=True)
                    await interaction.followup.send(embed=reference, ephemeral=True)
                except Exception:
                    logger.exception("help fallback DM failed")
                return
            except Exception:
                logger.exception("help DM failed")
                await interaction.response.send_message(
                    "Couldn't send the DM — try enabling DMs from server members.",
                    ephemeral=True,
                )
                return

            await interaction.response.send_message(
                "📬 Sent you a DM with a quick guide and every command!",
                ephemeral=True,
            )

        return help_cmd

    def _make_info_command(self):
        @discord.app_commands.command(
            name="info",
            description="Show server stats: members, channels, roles, boosts, age",
        )
        @discord.app_commands.describe(
            public="Post in the channel for everyone (default private). Add `public` as the last argument."
        )
        async def info_cmd(interaction: discord.Interaction, public: bool = False):
            guild = interaction.guild
            if guild is None:
                await interaction.response.send_message(
                    "This command only works inside a server.", ephemeral=True
                )
                return
            await interaction.response.defer(ephemeral=not public)
            bot = self.ctx.bot
            online = sum(
                1 for m in guild.members if getattr(m, "status", None) is not None and m.status != discord.Status.offline
            )
            bots = sum(1 for m in guild.members if m.bot)
            humans = guild.member_count - bots
            # guild.created_at is timezone-aware in discord.py, but guard
            # against naive datetimes (e.g. test fakes) before subtracting.
            now = discord.utils.utcnow()
            created = guild.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_days = (now - created).days
            # Guard every optional guild attribute so the command never 500s
            # on a partial guild object (e.g. a cached/partial fetch).
            owner = getattr(guild, "owner", None)
            premium_tier = getattr(guild, "premium_tier", 0) or 0
            premium_subs = getattr(guild, "premium_subscription_count", 0) or 0
            icon_url = getattr(getattr(guild, "icon", None), "url", None)
            embed = discord.Embed(
                title=f"ℹ️ {guild.name}",
                color=discord.Color.blurple(),
            )
            if icon_url:
                embed.set_thumbnail(url=icon_url)
            embed.add_field(name="Members", value=f"{guild.member_count:,}\n{humans:,} human · {bots:,} bot", inline=True)
            embed.add_field(name="Online", value=f"{online:,} right now", inline=True)
            embed.add_field(
                name="Channels",
                value=f"{len(guild.channels):,}\n{len(guild.text_channels):,} text · {len(guild.voice_channels):,} voice",
                inline=True,
            )
            embed.add_field(name="Roles", value=f"{len(guild.roles):,}", inline=True)
            embed.add_field(
                name="Boosts",
                value=f"{premium_subs:,} (Tier {premium_tier})",
                inline=True,
            )
            embed.add_field(name="Server age", value=f"{age_days:,} days", inline=True)
            if owner is not None:
                embed.add_field(name="Owner", value=f"{owner.mention}", inline=True)
            embed.add_field(
                name="Bark",
                value=f"v{getattr(bot, 'version', '?')} · {self.ctx.command_group}",
                inline=True,
            )
            embed.set_footer(text=f"Server ID {guild.id}")
            await interaction.followup.send(embed=embed, ephemeral=not public)

        return info_cmd

    def _make_stats_command(self):
        from services import server_stats

        def _ranked(items, fmt):
            """Render a ranked list with medal markers for the top 3."""
            medals = ("🥇", "🥈", "🥉")
            lines = []
            for i, item in enumerate(items[:3]):
                lines.append(f"{medals[i]} {fmt(item)}")
            return "\n".join(lines)

        @discord.app_commands.command(
            name="stats",
            description="Show server activity stats: top channels, games, rep, voice, and more",
        )
        @discord.app_commands.describe(
            public="Post in the channel for everyone (default private). Add `public` as the last argument."
        )
        async def stats_cmd(interaction: discord.Interaction, public: bool = False):
            guild = interaction.guild
            if guild is None:
                await interaction.response.send_message(
                    "This command only works inside a server.", ephemeral=True
                )
                return
            await interaction.response.defer(ephemeral=not public)
            guild_id = int(guild.id)

            channels = await server_stats.top_channel_30d(guild_id)
            games = await server_stats.top_game_month(guild_id)
            rep = await server_stats.top_reputation(guild_id)
            voice = await server_stats.top_voice_30d(guild_id)
            sessions = await server_stats.voice_session_summary(guild_id)
            rep_source = await server_stats.top_rep_source(guild_id)

            embed = discord.Embed(
                title=f"📊 {guild.name} — Activity Stats",
                color=discord.Color.blurple(),
                timestamp=datetime.now(timezone.utc),
            )

            # Row 1 — the three "activity" leaders.
            embed.add_field(
                name="Top Channels · 30d",
                value=_ranked(channels, lambda c: f"#{c['name']} — {c['count']:,}") if channels
                else "No message data yet.",
                inline=True,
            )
            embed.add_field(
                name="Top Games · month",
                value=_ranked(games, lambda g: f"**{g['name']}** ×{g['count']}") if games
                else "No game data yet.",
                inline=True,
            )
            embed.add_field(
                name="Highest Rep",
                value=_ranked(
                    rep,
                    lambda r: f"<@{r['user_id']}> — {r['score']:,.1f} pts",
                ) if rep else "No reputation data yet.",
                inline=True,
            )

            # Row 2 — voice + summary stats.
            embed.add_field(
                name="Top Voice · 30d",
                value=_ranked(
                    voice,
                    lambda v: f"<@{v['user_id']}> — {v['minutes']:,.0f} min",
                ) if voice else "No voice data yet.",
                inline=True,
            )
            embed.add_field(
                name="Voice Sessions · day",
                value=(
                    f"**Avg {sessions['avg_per_day']}**\n"
                    f"**Max {sessions['max_per_day']}**\n"
                    f"{sessions['days']} active days"
                ),
                inline=True,
            )
            embed.add_field(
                name="Top Rep Source",
                value=(
                    f"**{rep_source['source'].title()}**\n"
                    f"{rep_source['points']:,.1f} pts"
                    if rep_source["source"] != "none" else "No rep data yet."
                ),
                inline=True,
            )

            embed.set_footer(text=f"Server ID {guild.id}")
            await interaction.followup.send(embed=embed, ephemeral=not public)

        return stats_cmd

    async def enable(self) -> None:
        pass

    async def disable(self) -> None:
        pass
