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
    _queued_reply: "FakeMessage | None" = None

    async def wait_for(self, event, *, check=None, timeout=None):
        # If a reply was queued, hand it back (the caller's check must accept it).
        if self._queued_reply is not None:
            m = self._queued_reply
            self._queued_reply = None
            if check is None or check(m):
                return m
        raise asyncio.TimeoutError()


class FakeMessage:
    def __init__(self, content, author_id, channel_id, *, bot=False):
        self.content = content
        self.author = _FakeAuthor(author_id, bot=bot)
        self.channel = _FakeChannel(channel_id)
        self.deleted = False

    async def delete(self):
        self.deleted = True


class _FakeAuthor:
    def __init__(self, user_id, bot=False):
        self.id = user_id
        self.bot = bot


class _FakeChannel:
    def __init__(self, channel_id):
        self.id = channel_id


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, *a, **k):
        self.sent.append((a, k))


class FakeResponse:
    def __init__(self):
        self.modal = None
        self.sent = None

    async def send_modal(self, modal):
        self.modal = modal

    async def send_message(self, *a, **k):
        self.sent = (a, k)


class FakeInteraction:
    def __init__(self, *, user_id=999, channel_id=123, bot=None):
        self.response = FakeResponse()
        self.followup = FakeFollowup()
        self.guild_id = 123
        self.guild = None
        self.channel_id = channel_id
        self._user_id = user_id
        self.client = bot
        self._real_id = user_id

    @property
    def user(self):
        class M:
            def __init__(self, user_id):
                self.id = user_id

            @property
            def guild_permissions(self):
                return discord.Permissions.all()

        return M(self._user_id)


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


def test_command_select_uses_short_action_labels():
    d = _dispatcher()
    leaves = [d._registry[p] for p in d._module_paths["birthdays"]]
    select = interactions.BarkCommandSelect(d, leaves)
    labels = {option.value: option.label for option in select.options}

    assert labels["birthday channel"] == "Channel"
    assert labels["birthday set"] == "Set"
    assert all(not label.lower().startswith("birthday ") for label in labels.values())


def test_module_select_formats_names_for_people():
    d = _dispatcher()
    view = interactions.module_menu_view(d, guild_id=123)
    select = next(c for c in view.children if isinstance(c, interactions.BarkModuleSelect))
    labels = {option.value: option.label for option in select.options}

    assert labels["auto_voice"] == "Auto Voice"
    assert labels["role_manager"] == "Role Manager"


def test_command_select_starts_reply_capture_for_required_args():
    """A command with params but not in MODAL_ARG_COMMANDS uses reply-capture."""
    d = _dispatcher()
    leaf = d._registry["birthday set"]  # required day+month, not a modal command

    async def run():
        captured = _stub_dispatch(d)
        select = interactions.BarkCommandSelect(d, [leaf])
        select._values = ["birthday set"]  # noqa: SLF001
        inter = FakeInteraction()
        await select.callback(inter)
        return inter.response, captured

    response, captured = asyncio.run(run())
    assert isinstance(response.sent, tuple)  # ephemeral prompt was sent
    # Reply-capture must NOT open a modal.
    assert response.modal is None
    # And must NOT run the command yet (no reply arrived).
    assert captured == {}


def test_command_select_starts_reply_capture_for_optional_args_instead_of_running_default():
    """Picking `birthday channel` must not immediately disable announcements."""
    d = _dispatcher()
    leaf = d._registry["birthday channel"]

    async def run():
        captured = _stub_dispatch(d)
        select = interactions.BarkCommandSelect(d, [leaf])
        select._values = ["birthday channel"]  # noqa: SLF001
        inter = FakeInteraction()
        await select.callback(inter)
        return inter.response, captured

    response, captured = asyncio.run(run())
    # Reply-capture prompt, not a modal, and nothing dispatched yet.
    assert isinstance(response.sent, tuple)
    assert response.modal is None
    assert captured == {}


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


# ── Reply capture (privacy-preserving arg collection) ──


def test_command_uses_modal_classification():
    """Only MODAL_ARG_COMMANDS with params get the modal; others are reply-capture."""
    d = _dispatcher()
    leaf = d._registry["birthday set"]  # params, but NOT a modal command

    class _Leaf:
        def __init__(self, path, params):
            self.path = path
            self.command = type("C", (), {"parameters": params})()

    # A multi-field config command keeps the modal.
    modal_leaf = _Leaf("announce", [object(), object()])
    assert interactions.command_uses_modal(modal_leaf) is True
    # A simple-arg command is reply-capture.
    assert interactions.command_uses_modal(leaf) is False
    # A command with no params is neither.
    noarg = _Leaf("help", [])
    assert interactions.command_uses_modal(noarg) is False


def test_reply_capture_captures_reply_deletes_and_dispatches():
    """Happy path: prompt sent, user's reply captured+deleted, command dispatched."""
    d = _dispatcher()
    leaf = d._registry["birthday set"]

    bot = FakeBot()
    bot._queued_reply = FakeMessage("12 8", author_id=999, channel_id=123)

    async def run():
        captured = _stub_dispatch(d)
        inter = FakeInteraction(user_id=999, channel_id=123, bot=bot)
        await interactions._collect_args_by_reply(d, inter, leaf)
        return captured, inter, bot._queued_reply

    captured, inter, reply = asyncio.run(run())
    # The prompt embed was sent (ephemeral).
    assert inter.response.sent is not None
    # The user's reply was deleted (privacy).
    assert reply is None  # consumed by wait_for
    # The command dispatched with the reply content as args.
    assert captured["command"] == "birthday set"
    assert captured["args"] == "12 8"


def test_reply_capture_ignores_other_users_and_bots():
    """The check only accepts the invoker's non-bot, non-empty message."""
    d = _dispatcher()
    leaf = d._registry["birthday set"]

    bot = FakeBot()
    # First a message from the WRONG user, then a bot message, then the real one.
    bot._queued_reply = FakeMessage("12 8", author_id=111, channel_id=123)

    async def run():
        captured = _stub_dispatch(d)
        inter = FakeInteraction(user_id=999, channel_id=123, bot=bot)
        await interactions._collect_args_by_reply(d, inter, leaf)
        return captured

    # The wrong-user message fails the check -> wait_for times out (no dispatch).
    captured = asyncio.run(run())
    assert captured == {}


def test_reply_capture_cancel_aborts_without_dispatch():
    """Replying 'cancel' aborts the command and does not dispatch."""
    d = _dispatcher()
    leaf = d._registry["birthday set"]

    bot = FakeBot()
    bot._queued_reply = FakeMessage("cancel", author_id=999, channel_id=123)

    async def run():
        captured = _stub_dispatch(d)
        inter = FakeInteraction(user_id=999, channel_id=123, bot=bot)
        await interactions._collect_args_by_reply(d, inter, leaf)
        return captured, inter

    captured, inter = asyncio.run(run())
    assert captured == {}
    assert "Cancelled" in inter.followup.sent[0][0][0]


def test_reply_capture_times_out_gracefully():
    """No reply -> timeout message, nothing dispatched."""
    d = _dispatcher()
    leaf = d._registry["birthday set"]

    bot = FakeBot()  # nothing queued -> wait_for raises TimeoutError

    async def run():
        captured = _stub_dispatch(d)
        inter = FakeInteraction(user_id=999, channel_id=123, bot=bot)
        await interactions._collect_args_by_reply(d, inter, leaf)
        return captured, inter

    captured, inter = asyncio.run(run())
    assert captured == {}
    assert "Timed out" in inter.followup.sent[0][0][0]
