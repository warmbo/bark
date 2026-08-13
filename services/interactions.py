"""Interactive response helpers for slash commands.

Bark's slash responses become interactive so a user can progress by clicking a
button, picking from a select menu, or adding a reaction. This module provides
the reusable pieces; individual module handlers attach them to their embeds.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import discord

logger = logging.getLogger("bark.interactions")


class BarkCommandSelect(discord.ui.Select):
    """A select menu that re-runs a command through the /bark dispatcher.

    Drop it onto any response to let the user pick and run another module
    command without re-typing the slash command.
    """

    def __init__(
        self,
        dispatch: Callable[[discord.Interaction, str, str], Any],
        paths: list[str],
        placeholder: str = "Run another command…",
    ) -> None:
        options = [discord.SelectOption(label=p[:100], value=p) for p in paths[:25]]
        if not options:
            options = [discord.SelectOption(label="No commands", value="_none")]
        super().__init__(placeholder=placeholder, options=options, min_values=1, max_values=1)
        self._dispatch = dispatch

    async def callback(self, interaction: discord.Interaction) -> None:
        # Do NOT defer: let the re-dispatched command's handler provide the
        # response to this component interaction. Fall back to an error reply
        # if the dispatch raised before responding.
        try:
            await self._dispatch(interaction, self.values[0], "")
        except Exception:
            logger.exception("Command picker dispatch failed for %r", self.values[0])
            try:
                await interaction.response.send_message(
                    "That command failed to run.", ephemeral=True
                )
            except Exception:
                await interaction.followup.send(
                    "That command failed to run.", ephemeral=True
                )


class BarkActionView(discord.ui.View):
    """A view carrying the command-select menu plus an optional custom row."""

    def __init__(self, dispatch, paths: list[str], *, timeout: float = 300.0) -> None:
        super().__init__(timeout=timeout)
        self.add_item(BarkCommandSelect(dispatch, paths))


def attach_command_picker(
    dispatcher,
    paths: list[str] | None = None,
) -> BarkActionView:
    """Build a view whose select re-runs a command via the dispatcher."""
    if paths is None:
        paths = sorted(dispatcher._registry.keys())  # noqa: SLF001

    def _dispatch(interaction: discord.Interaction, command: str, args: str) -> Any:
        return dispatcher.dispatch(interaction, command, args)

    return BarkActionView(_dispatch, paths)
