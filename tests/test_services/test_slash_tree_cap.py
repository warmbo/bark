"""Regression: the /bark command tree must fit Discord's limits so sync works.

Live incident (2026-09-01): a native subcommand-group tree for /bark exceeded
Discord's 8000-byte global-command payload cap (moderation alone was 3.8KB,
the whole tree 9KB+ canonical-only). `tree.sync()` failed with 50035
"Command exceeds maximum size (8000)", so the new signature never reached
Discord and every /bark interaction was rejected with CommandSignatureMismatch
("Couldn't run that command — check the arguments and try again").

The fix: register the flat single-command dispatcher (string command/args
options) — Bark's intended design — which fits trivially and whose autocomplete
still exposes every module command including `/bark birthday set`.
"""
import importlib
import json

import discord

from modules.base import BarkModule
from services.slash_dispatcher import SlashDispatcher

CORE = [
    "announcements",
    "auto_voice",
    "help",
    "logging",
    "moderation",
    "reputation",
    "role_manager",
    "speak",
    "welcome",
]
PLUGINS = ["birthdays"]


class FakeManager:
    def is_plugin(self, name):
        return name in PLUGINS

    def _command_enabled_check(self, name):
        return lambda _i: True


class FakeBot:
    pass


def _module_class(module_name):
    if module_name in PLUGINS:
        mod = importlib.import_module(f"data.plugins.{module_name}")
    else:
        mod = importlib.import_module(f"modules.{module_name}.module")
    return next(
        v
        for v in vars(mod).values()
        if isinstance(v, type)
        and issubclass(v, BarkModule)
        and v is not BarkModule
        and hasattr(v, "get_commands")
    )


def _dispatcher():
    d = SlashDispatcher(FakeBot(), FakeManager())
    for name in CORE + PLUGINS:
        d.register_module(name, _module_class(name).__new__(_module_class(name)))
    return d


def _flat_payload_bytes(cmd) -> int:
    """Serialize the flat command the way discord.py's tree sync does:
    {name, description, type, options}. The flat command has two string
    options (command + args)."""
    opts = []
    for o in getattr(cmd, "options", []):
        opts.append({"name": o.name, "description": o.description or "", "type": 3, "required": o.required})
    payload = {"name": cmd.name, "description": cmd.description or "", "type": 1, "options": opts}
    return len(json.dumps(payload, separators=(",", ":")).encode())


def test_flat_bark_payload_fits_discord_cap():
    """The registered /bark command must serialize under Discord's 8000-byte
    global-command limit (this was the 2026-09-01 sync failure)."""
    cmd = _dispatcher().build_command("bark")
    size = _flat_payload_bytes(cmd)
    assert size <= 8000, f"/bark payload is {size} bytes (> 8000)"


def test_flat_bark_resolves_birthday_set_path():
    """`/bark birthday set` must resolve through the flat dispatcher — the
    exact syntax that failed for users on 2026-09-01."""
    d = _dispatcher()
    assert "birthday set" in d._registry
    # The flat command's 'command' option is a PLAIN string so Discord binds
    # free-typed text (e.g. `/bark help`) without requiring a click. An
    # autocomplete option would leave typed text pending (2026-09-01 report).
    cmd = d.build_command("bark")
    param = next(p for p in cmd.parameters if p.name == "command")
    assert param.type is discord.AppCommandOptionType.string
    assert not param.autocomplete  # False = no autocomplete handler attached
    assert param.required is False
