"""Tests for Batch C hardening: image sniffing, link-log dedupe, and
_get_setting failure visibility."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.logging.module import LoggingModule
from modules.moderation.module import ModerationModule
from services.image_validate import is_image, sniff_image

# ── Image magic-byte sniffing ───────────────────────────


def test_sniff_image_magic_bytes():
    assert sniff_image(b"\x89PNG\r\n\x1a\n" + b"data") == ".png"
    assert sniff_image(b"\xff\xd8\xff\xe0" + b"data") == ".jpg"
    assert sniff_image(b"GIF89a" + b"data") == ".gif"
    assert sniff_image(b"RIFF" + b"\x00" * 4 + b"WEBP" + b"x") == ".webp"
    assert sniff_image(b"<html>not an image</html>") is None
    assert sniff_image(b"") is None
    assert not is_image(b"plain text pretending to be an image")
    assert is_image(b"\x89PNG\r\n\x1a\n" + b"x")


# ── link_posted dedupe ──────────────────────────────────


@pytest.mark.asyncio
async def test_link_posted_deduped_per_author_link():
    ctx = MagicMock()
    ctx.log_audit = AsyncMock()
    module = LoggingModule(ctx)  # type: ignore[arg-type]

    def _msg():
        return SimpleNamespace(
            id=1,
            content="https://example.com/x",
            author=SimpleNamespace(id=100, bot=False, __str__=lambda s: "u"),
            guild=SimpleNamespace(id=1),
            channel=SimpleNamespace(id=2, __str__=lambda s: "#c"),
            attachments=[],
        )

    await module._on_message("discord_message", message=_msg())
    await module._on_message("discord_message", message=_msg())  # same link again
    assert ctx.log_audit.await_count == 1, "duplicate link within window must not re-log"


# ── _get_setting failure visibility ─────────────────────


@pytest.mark.asyncio
async def test_get_setting_warns_once_on_config_failure(caplog):
    class _FailingCtx:
        async def get_module_config(self, name, guild_id):
            raise RuntimeError("db down")

    module = ModerationModule(_FailingCtx())  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING, logger="bark.modules.moderation"):
        assert await module._get_setting(1, "anti_raid", "enabled", True) is True
        assert await module._get_setting(1, "anti_raid", "enabled", True) is True
    warnings = [r for r in caplog.records if "Failed to load config" in r.getMessage()]
    assert len(warnings) == 1, "failure must be surfaced once, not per call"
