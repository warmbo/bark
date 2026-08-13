"""Tests for the reaction-based embed paginator used by guidance menus."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from services.paginator import EMOJI_NEXT, EMOJI_PREV, ReactionPaginator


def _user(id_: int, *, bot: bool = False) -> MagicMock:
    u = MagicMock()
    u.id = id_
    u.bot = bot
    return u


def _make_msg() -> MagicMock:
    msg = MagicMock()
    msg.id = 111
    msg.edit = AsyncMock()
    msg.add_reaction = AsyncMock()
    return msg


def _send_two_pages():
    pag = ReactionPaginator()
    msg = _make_msg()
    interaction = MagicMock()
    interaction.user.id = 42
    interaction.response.send_message = AsyncMock(return_value=msg)
    asyncio.run(pag.send(interaction, [discord.Embed(title="p1"), discord.Embed(title="p2")]))
    return pag, msg


def test_send_arms_reactions_when_multiple_pages():
    pag, msg = _send_two_pages()
    assert msg.add_reaction.await_count == 2
    assert 111 in pag._sessions


def test_send_skips_reactions_for_single_page():
    pag = ReactionPaginator()
    msg = _make_msg()
    interaction = MagicMock()
    interaction.user.id = 42
    interaction.response.send_message = AsyncMock(return_value=msg)
    asyncio.run(pag.send(interaction, [discord.Embed(title="p1")]))
    assert msg.add_reaction.await_count == 0


def test_navigate_next_edits_to_next_page():
    pag, msg = _send_two_pages()
    msg.edit.reset_mock()
    reaction = MagicMock()
    reaction.message = msg
    reaction.emoji = EMOJI_NEXT
    reaction.remove = AsyncMock()
    asyncio.run(pag.on_reaction_add(reaction, _user(42)))
    msg.edit.assert_awaited_once()
    assert msg.edit.await_args.kwargs["embed"].title == "p2"
    reaction.remove.assert_awaited_once()


def test_navigate_prev_wraps_to_last_page():
    pag, msg = _send_two_pages()
    msg.edit.reset_mock()
    reaction = MagicMock()
    reaction.message = msg
    reaction.emoji = EMOJI_PREV
    reaction.remove = AsyncMock()
    asyncio.run(pag.on_reaction_add(reaction, _user(42)))
    msg.edit.assert_awaited_once()
    assert msg.edit.await_args.kwargs["embed"].title == "p2"  # wraps from page 0


def test_ignores_non_author_reactions():
    pag, msg = _send_two_pages()
    msg.edit.reset_mock()
    reaction = MagicMock()
    reaction.message = msg
    reaction.emoji = EMOJI_NEXT
    reaction.remove = AsyncMock()
    asyncio.run(pag.on_reaction_add(reaction, _user(99)))
    msg.edit.assert_not_awaited()


def test_ignores_bot_reactions():
    pag, msg = _send_two_pages()
    msg.edit.reset_mock()
    reaction = MagicMock()
    reaction.message = msg
    reaction.emoji = EMOJI_NEXT
    asyncio.run(pag.on_reaction_add(reaction, _user(42, bot=True)))
    msg.edit.assert_not_awaited()


@pytest.mark.asyncio
async def test_ignores_untracked_message():
    pag = ReactionPaginator()
    msg = _make_msg()
    reaction = MagicMock()
    reaction.message = msg
    reaction.emoji = EMOJI_NEXT
    await pag.on_reaction_add(reaction, _user(1))
    msg.edit.assert_not_awaited()
