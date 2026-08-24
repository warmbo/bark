"""Regression test: embed field values must stay under Discord's 1024-char cap.

The live incident (2026-08-24): `/bark-dev` bare overview crashed with
50035 "fields.4.value: Must be 1024 or fewer in length" — the Moderation
field hit exactly 1025 chars once every moderation subcommand line was joined.
The chunker counted FIELDS per page, not characters, so one huge module could
still blow the limit.
"""
from types import SimpleNamespace

import pytest

from services.slash_dispatcher import Leaf, SlashDispatcher

LIMIT = 1024


class FakeManager:
    def is_plugin(self, name):
        return False

    def _command_enabled_check(self, name):
        return lambda _i: True


class FakeBot:
    pass


def make_leaf(path, param_names, description):
    cmd = SimpleNamespace(
        parameters=[SimpleNamespace(name=p) for p in param_names],
        description=description,
    )
    return Leaf(command=cmd, check=None, path=path, module_name="moderation")


@pytest.fixture()
def dispatcher():
    return SlashDispatcher(FakeBot(), FakeManager())


def test_chunker_splits_oversized_module(dispatcher):
    """A single command-heavy module must be split across pages so every
    rendered field stays under the 1024-char embed limit."""
    leaves = [
        make_leaf(
            f"cmd{i}",
            ["member", "channel", "reason", "duration", "extra"],
            f"Long description for command number {i} that pads out the line",
        )
        for i in range(16)
    ]

    chunks = dispatcher._chunk_by_module(leaves)
    seen = 0
    for page in chunks:
        for module_name, ls in page:
            value = "\n".join(dispatcher._command_line(leaf) for leaf in ls)
            assert len(value) <= LIMIT, (
                f"embed field '{module_name}' is {len(value)} chars (> {LIMIT})"
            )
            seen += len(ls)
    # No leaves lost or duplicated by the split.
    assert seen == len(leaves)


def test_chunker_preserves_field_cap(dispatcher):
    """Small modules still group up to ``max_fields`` per page."""
    leaves = [make_leaf(f"cmd{i}", [], f"Short {i}") for i in range(10)]
    chunks = dispatcher._chunk_by_module(leaves, max_fields=6)
    for page in chunks:
        assert len(page) <= 6


def test_real_moderation_module_fits():
    """Integration: the real Moderation module's overview lines must render
    within the embed-field cap (this was the live 50035 failure)."""
    import importlib
    import os

    os.environ.setdefault("BARK_BOT_TOKEN", "")
    from modules.base import BarkModule

    d = SlashDispatcher(FakeBot(), FakeManager())
    mod = importlib.import_module("modules.moderation.module")
    cls = next(
        v
        for v in vars(mod).values()
        if isinstance(v, type) and issubclass(v, BarkModule) and v is not BarkModule
    )
    d.register_module("moderation", cls.__new__(cls))

    class FakeManager2(FakeManager):
        def is_plugin(self, name):
            return False

    d.manager = FakeManager2()

    for embed in d._build_overview_pages(guild_id=None):
        for field in embed.fields:
            assert len(field.value) <= LIMIT, (
                f"overview embed field '{field.name}' is {len(field.value)} chars"
                f" (> {LIMIT})"
            )