"""Regression: paginator must resolve the REAL message from a slash response.

discord.py 2.4+ changed ``InteractionResponse.send_message`` to return an
``InteractionCallbackResponse`` placeholder instead of the sent message: it
carries a SYNTHETIC id that does not match the real message and has no
``add_reaction`` method. The paginator previously used that return value
directly, so sessions were tracked under a fake id (reaction navigation never
matched) and arming the ◀ ▶ reactions raised AttributeError every time —
pagination was silently broken on every guidance menu.

The fix fetches the actual message via ``interaction.original_response()``
after a successful initial response.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from services.paginator import EMOJI_NEXT, ReactionPaginator


def _user(id_: int) -> MagicMock:
    u = MagicMock()
    u.id = id_
    u.bot = False
    return u


def _placeholder() -> MagicMock:
    """Stand-in for discord.py's InteractionCallbackResponse: fake id, and
    ``add_reaction`` is NOT defined on the real class (attribute access raises
    AttributeError), so assert it is never reached."""
    resp = MagicMock()
    resp.id = 999999  # synthetic id, deliberately not the real message id
    return resp


def _real_message(message_id: int) -> MagicMock:
    msg = MagicMock()
    msg.id = message_id
    msg.edit = AsyncMock()
    msg.add_reaction = AsyncMock()
    return msg


def test_send_resolves_real_message_from_original_response():
    """send_message returning a placeholder must not leak into the session."""
    pag = ReactionPaginator()
    placeholder = _placeholder()
    real = _real_message(111)
    interaction = MagicMock()
    interaction.user.id = 42
    interaction.response.send_message = AsyncMock(return_value=placeholder)
    interaction.original_response = AsyncMock(return_value=real)

    asyncio.run(pag.send(interaction, [discord.Embed(title="p1"), discord.Embed(title="p2")]))

    # The real message is fetched and used for reactions…
    interaction.original_response.assert_awaited_once()
    real.add_reaction.assert_awaited()
    assert placeholder.add_reaction.call_count == 0
    # …and the session is tracked under the REAL message id, not the fake one.
    assert 111 in pag._sessions
    assert 999999 not in pag._sessions


def test_send_tracks_real_id_so_navigation_matches():
    """A reaction arriving on the real message must drive that session."""
    pag = ReactionPaginator()
    real = _real_message(111)
    interaction = MagicMock()
    interaction.user.id = 42
    interaction.response.send_message = AsyncMock(return_value=_placeholder())
    interaction.original_response = AsyncMock(return_value=real)

    asyncio.run(pag.send(interaction, [discord.Embed(title="p1"), discord.Embed(title="p2")]))

    reaction = MagicMock()
    reaction.message = real
    reaction.emoji = EMOJI_NEXT
    reaction.remove = AsyncMock()
    asyncio.run(pag.on_reaction_add(reaction, _user(42)))
    real.edit.assert_awaited_once()
    assert real.edit.await_args.kwargs["embed"].title == "p2"


def test_send_falls_back_to_followup_when_response_already_used():
    """The followup path (response.send_message raising) still works and uses
    the followup's real message for reactions + session tracking."""
    pag = ReactionPaginator()
    real = _real_message(222)
    interaction = MagicMock()
    interaction.user.id = 42
    interaction.response.send_message = AsyncMock(side_effect=RuntimeError("already used"))
    interaction.followup.send = AsyncMock(return_value=real)

    asyncio.run(pag.send(interaction, [discord.Embed(title="p1"), discord.Embed(title="p2")]))

    interaction.followup.send.assert_awaited_once()
    real.add_reaction.assert_awaited()
    assert 222 in pag._sessions
    # The placeholder path was never taken.
    interaction.original_response.assert_not_called()


@pytest.mark.asyncio
async def test_single_page_send_never_fetches_original_response():
    """Single-page menus skip reaction arming entirely — and must not need the
    real message for reactions, but still track the true id."""
    pag = ReactionPaginator()
    real = _real_message(333)
    interaction = MagicMock()
    interaction.user.id = 42
    interaction.response.send_message = AsyncMock(return_value=_placeholder())
    interaction.original_response = AsyncMock(return_value=real)

    await pag.send(interaction, [discord.Embed(title="p1")])

    real.add_reaction.assert_not_awaited()
    assert 333 in pag._sessions
    assert 999999 not in pag._sessions
