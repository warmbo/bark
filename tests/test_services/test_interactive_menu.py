"""Tests for the interactive /bark menu (module select -> command select -> form).

The flat ``/bark`` dispatcher is kept; menus make it interactive so users pick
from selects and fill a form modal instead of typing ``command``/``args``.
"""

import asyncio
import importlib

import discord

from modules.base import BarkModule
from services import interactions
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

    def is_enabled_for_guild(self, guild_id, name):
        return True


class FakeBot:
    paginator = None


class FakeResponse:
    def __init__(self):
        self.modal = None
        self.sent = None

    async def send_modal(self, modal):
        self.modal = modal

    async def send_message(self, *a, **k):
        self.sent = (a, k)


class FakeInteraction:
    def __init__(self):
        self.response = FakeResponse()
        self.guild_id = 123
        self.guild = None

    @property
    def user(self):
        class M:
            @property
            def guild_permissions(self):
                return discord.Permissions.all()

        return M()


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


def _stub_dispatch(d):
    captured = {}

    async def fake_dispatch(interaction, command, args=""):
        captured["command"] = command
        captured["args"] = args

    d.dispatch = fake_dispatch  # type: ignore[method-assign]
    return captured


def test_module_menu_view_lists_enabled_modules():
    d = _dispatcher()
    view = interactions.module_menu_view(d, guild_id=123)
    select = next(c for c in view.children if isinstance(c, interactions.BarkModuleSelect))
    names = {o.value for o in select.options}
    assert "moderation" in names
    assert "birthdays" in names
    assert "help" in names


def test_command_menu_view_has_select_and_back_button():
    d = _dispatcher()
    leaves = [d._registry[p] for p in d._module_paths["birthdays"]]
    view = interactions.command_menu_view(d, leaves, guild_id=123)
    kinds = [type(c) for c in view.children]
    assert interactions.BarkCommandSelect in kinds
    assert interactions.BackToModulesButton in kinds


def test_command_select_opens_modal_for_required_args():
    d = _dispatcher()
    leaf = d._registry["birthday set"]  # required day+month

    async def run():
        select = interactions.BarkCommandSelect(d, [leaf])
        select._values = ["birthday set"]  # noqa: SLF001
        inter = FakeInteraction()
        await select.callback(inter)
        return inter.response.modal

    modal = asyncio.run(run())
    assert isinstance(modal, interactions.BarkArgsModal)
    assert set(modal._inputs) == {"day", "month"}


def test_command_select_runs_directly_when_no_required_args():
    d = _dispatcher()
    leaf = d._registry.get("help")
    assert leaf is not None

    async def run():
        captured = _stub_dispatch(d)
        select = interactions.BarkCommandSelect(d, [leaf])
        select._values = ["help"]  # noqa: SLF001
        inter = FakeInteraction()
        await select.callback(inter)
        return inter.response.modal, captured

    modal, captured = asyncio.run(run())
    assert modal is None  # no required args -> no form
    assert captured["command"] == "help"
    assert captured["args"] == ""


def test_args_modal_builds_ordered_args_string():
    d = _dispatcher()
    leaf = d._registry["birthday set"]

    modal = interactions.BarkArgsModal(d, leaf)
    assert set(modal._inputs) == {"day", "month"}
    modal._inputs["day"]._value = "10"  # noqa: SLF001
    modal._inputs["month"]._value = "3"  # noqa: SLF001

    async def run():
        captured = _stub_dispatch(d)
        inter = FakeInteraction()
        await modal.on_submit(inter)
        return captured

    captured = asyncio.run(run())
    assert captured["command"] == "birthday set"
    assert captured["args"] == "10 3"
