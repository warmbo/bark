"""Help module — `bark!help` DMs every available text command.

Walks the live prefix-command table (the exact commands the bot accepts after
its configured prefix), builds a command reference embed, and DMs it to the
invoker along with dashboard / invite access info. Falls back to an ephemeral
in-channel copy when the user has DMs disabled.
"""

from __future__ import annotations

import logging

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
            )
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
                value=f"Run `{prefix}help` anytime — the bot DMs you this list.",
                inline=False,
            )
            reference.set_footer(text=f"Bark {self.name} v{self.version}")

            try:
                await interaction.user.send(embed=instructions)
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

    async def enable(self) -> None:
        pass

    async def disable(self) -> None:
        pass
