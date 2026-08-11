"""Help module — `/bark help` DMs every available slash command.

Walks the live command tree (the exact commands Discord sees), builds a
command reference embed, and DMs it to the invoker along with dashboard /
invite access info. Falls back to an ephemeral in-channel copy when the
user has DMs disabled.
"""

from __future__ import annotations

import logging

import discord

from config import config
from modules.base import BarkModule, CommandRegistration

logger = logging.getLogger("bark.help")


def _walk_commands(command, path: list[str], out: list[tuple[str, str]]) -> None:
    """Collect (full path, description) for every leaf command."""
    if getattr(command, "commands", None):
        for sub in command.commands:
            _walk_commands(sub, path + [sub.name], out)
    else:
        out.append(("/" + " ".join(path), command.description or ""))


class HelpModule(BarkModule):
    name = "help"
    version = "1.0.0"
    description = "DMs every available slash command plus dashboard info."

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(
                name="help",
                description="Send a DM with every slash command and dashboard info",
            )
        ]

    def _make_help_command(self):
        @discord.app_commands.command(
            name="help",
            description="Send a DM with every slash command and dashboard info",
        )
        async def help_cmd(interaction: discord.Interaction):
            commands: list[tuple[str, str]] = []
            tree = getattr(self.ctx.bot, "tree", None)
            if tree is not None:
                for cmd in tree.get_commands():
                    if cmd.name == "bark":
                        _walk_commands(cmd, ["bark"], commands)

            public_url = getattr(config.dashboard, "public_url", "")
            instructions = discord.Embed(
                title="🐺 How to use Bark",
                description=(
                    "Bark is a dashboard-first server manager: you run it from "
                    "this dashboard, and command it from Discord with slash "
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
                name="4. Use /bark commands in Discord",
                value=(
                    "Everything lives under the global **`/bark`** group — no "
                    "prefix to remember. Try `/bark help` (this DM), `/bark "
                    "warn`, `/bark announce`, `/bark serverinfo`…"
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
                    value=(
                        f"**Dashboard:** {public_url}\n"
                        f"**Invite:** {public_url}/invite"
                    ),
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
                value="Run `/bark help` anytime — the bot DMs you this list.",
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
