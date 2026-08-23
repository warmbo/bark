"""Reaction-based embed pagination for guidance menus.

A user can flip between pages of a guidance embed by reacting with the ◀ ▶
arrow emojis. Each paginated message is tracked by message id so the bot can
edit the embed in place as the invoker navigates. Only the invoker may navigate
(others' reactions are ignored), and the nav reactions are removed after each
click so they can be pressed repeatedly.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import discord

logger = logging.getLogger("bark.paginator")

EMOJI_PREV = "◀"
EMOJI_NEXT = "▶"

# Paginated menus are guidance embeds — nobody pages through them hours later.
# Sessions older than this are evicted so the tracking dict cannot grow without
# bound on long-running instances (``close`` is only called explicitly, and
# nothing calls it today).
SESSION_TTL_SECONDS = 3600.0


class ReactionPaginator:
    """Tracks paginated messages and drives them from raw arrow reactions."""

    def __init__(self) -> None:
        self._sessions: dict[int, dict[str, Any]] = {}

    def _prune_expired(self) -> None:
        now = time.monotonic()
        expired = [
            mid
            for mid, s in self._sessions.items()
            if now - s.get("created", now) > SESSION_TTL_SECONDS
        ]
        for mid in expired:
            del self._sessions[mid]

    async def send(
        self,
        interaction: discord.Interaction,
        pages: list[discord.Embed],
        *,
        view: discord.ui.View | None = None,
        author_id: int | None = None,
    ) -> None:
        """Send a paginated embed (non-ephemeral) and arm the ◀ ▶ reactions.

        ``interaction.response`` must not have been used yet (guidance is the
        initial response). Falls back to a followup if it already was.
        """
        if not pages:
            pages = [discord.Embed(title="No information available")]
        kwargs: dict[str, Any] = {"embed": pages[0]}
        if view is not None:
            kwargs["view"] = view
        try:
            msg = await interaction.response.send_message(**kwargs)
        except Exception:
            logger.debug("response already used; sending paginated menu as followup")
            msg = await interaction.followup.send(**kwargs)
        self._prune_expired()
        self._sessions[msg.id] = {
            "pages": pages,
            "index": 0,
            "created": time.monotonic(),
            "author_id": author_id or getattr(getattr(interaction, "user", None), "id", None),
        }
        # Only arm navigation when there's actually something to page through.
        if len(pages) > 1:
            try:
                await msg.add_reaction(EMOJI_PREV)
                await msg.add_reaction(EMOJI_NEXT)
            except Exception:
                logger.exception("Could not add pagination reactions to message %s", msg.id)

    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User) -> None:
        """Handle a ◀ ▶ reaction on a tracked paginated message."""
        if getattr(user, "bot", False):
            return
        self._prune_expired()
        session = self._sessions.get(reaction.message.id)
        if session is None:
            return
        if user.id != session["author_id"]:
            return
        emoji = str(reaction.emoji)
        total = len(session["pages"])
        if emoji == EMOJI_PREV:
            session["index"] = (session["index"] - 1) % total
        elif emoji == EMOJI_NEXT:
            session["index"] = (session["index"] + 1) % total
        else:
            return
        await reaction.message.edit(embed=session["pages"][session["index"]])
        try:
            await reaction.remove(user)
        except Exception:
            pass

    def close(self, message_id: int) -> None:
        self._sessions.pop(message_id, None)
