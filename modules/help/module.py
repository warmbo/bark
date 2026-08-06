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

            embed = discord.Embed(
                title="🐺 Bark — Command Reference",
                color=discord.Color.blurple(),
            )
            if commands:
                embed.description = "\n".join(
                    f"`{path}`{' — ' + desc if desc else ''}" for path, desc in commands
                )
            else:
                embed.description = "No commands registered yet."

            access_lines = []
            if getattr(config.dashboard, "public_url", ""):
                access_lines.append(f"**Dashboard:** {config.dashboard.public_url}")
            if getattr(config.dashboard, "invite_url", ""):
                access_lines.append(f"**Invite:** {config.dashboard.invite_url}")
            if access_lines:
                embed.add_field(
                    name="Manage Bark",
                    value="\n".join(access_lines),
                    inline=False,
                )
            embed.add_field(
                name="Tip",
                value="Run `/bark help` anytime — the bot DMs you this list.",
                inline=False,
            )
            embed.set_footer(text=f"Bark {self.name} v{self.version}")

            try:
                await interaction.user.send(embed=embed)
            except discord.Forbidden:
                await interaction.response.send_message(
                    "I couldn't DM you (DMs from server members may be off). "
                    "Here's the command list instead:",
                    ephemeral=True,
                )
                try:
                    await interaction.followup.send(embed=embed, ephemeral=True)
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
                "📬 Sent you a DM with every command!", ephemeral=True
            )

        return help_cmd

    async def enable(self) -> None:
        pass

    async def disable(self) -> None:
        pass
