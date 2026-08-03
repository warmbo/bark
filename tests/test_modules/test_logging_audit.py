"""Logging module abnormal-activity audit persistence tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.logging.module import LoggingModule
from services.bark_context import BarkContext
from services.event_bus import EventBus


def _bot():
    bot = MagicMock()
    bot.get_guild.return_value = SimpleNamespace(id=123)
    return bot


def _module():
    ctx = BarkContext(_bot(), EventBus())
    ctx.log_audit = AsyncMock()
    module = LoggingModule(ctx)
    module._get_channel = AsyncMock(return_value=SimpleNamespace(send=AsyncMock()))
    module._send = AsyncMock()
    return module


def _author(mid=42, name="cody"):
    return SimpleNamespace(id=mid, bot=False, mention=f"<@{mid}>", __str__=lambda s: name)


@pytest.mark.asyncio
async def test_message_edit_logs_audit_event():
    module = _module()
    author = _author()
    before = SimpleNamespace(
        id=1,
        guild=SimpleNamespace(id=123),
        channel=SimpleNamespace(id=9, mention="#gen"),
        author=author,
        content="old text",
    )
    after = SimpleNamespace(
        id=1, guild=before.guild, channel=before.channel, author=author, content="new text"
    )

    await module._on_message_edit("discord_message_edit", before=before, after=after)
    module.ctx.log_audit.assert_awaited_once()
    args = module.ctx.log_audit.await_args
    assert args.args[1] == "message_edit"
    assert args.args[2] == "42"
    assert args.kwargs["details"]["before"] == "old text"
    assert args.kwargs["details"]["after"] == "new text"


@pytest.mark.asyncio
async def test_message_delete_logs_audit_event():
    module = _module()
    msg = SimpleNamespace(
        id=2,
        guild=SimpleNamespace(id=123),
        channel=SimpleNamespace(id=9, mention="#gen"),
        author=_author(),
        content="bye bye",
        attachments=[],
    )
    await module._on_message_delete("discord_message_delete", message=msg)
    module.ctx.log_audit.assert_awaited_once()
    args = module.ctx.log_audit.await_args
    assert args.args[1] == "message_delete"
    assert args.kwargs["details"]["content"] == "bye bye"


@pytest.mark.asyncio
async def test_link_posted_logs_audit_event():
    module = _module()
    msg = SimpleNamespace(
        id=3,
        guild=SimpleNamespace(id=123),
        channel=SimpleNamespace(id=9, mention="#gen"),
        author=_author(),
        content="check https://example.com/page and https://second.dev/x",
        attachments=[],
    )
    await module._on_message("discord_message", message=msg)
    module.ctx.log_audit.assert_awaited_once()
    args = module.ctx.log_audit.await_args
    assert args.args[1] == "link_posted"
    assert args.kwargs["details"]["link"] == "https://example.com/page"
    assert len(args.kwargs["details"]["links"]) == 2


@pytest.mark.asyncio
async def test_plain_message_without_link_does_not_log():
    module = _module()
    msg = SimpleNamespace(
        id=4,
        guild=SimpleNamespace(id=123),
        channel=SimpleNamespace(id=9, mention="#gen"),
        author=_author(),
        content="just chatting, no links here",
        attachments=[],
    )
    await module._on_message("discord_message", message=msg)
    module.ctx.log_audit.assert_not_awaited()
