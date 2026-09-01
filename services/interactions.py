"""Interactive response helpers for slash commands.

Bark's flat ``/bark`` dispatcher is the single registered command; this module
makes it feel native by responding with an interactive menu instead of making
the user type ``command``/``args``:

    /bark                     -> overview embed + a MODULE select menu
    pick a module             -> that module's commands as a COMMAND select
    pick a command w/o args   -> runs immediately
    pick a command w/ args    -> collects the arguments privately

Arguments are collected one of two ways, chosen by the command:

* **reply capture** (default) — Bark posts an ephemeral prompt, you reply to
  it as a normal message, and Bark deletes your reply once the command runs.
  Keeps bot↔user interaction private and auto-cleaning, and feels natural on
  mobile. Used for sensitive (moderation, voice) and simple one-arg commands.
* **form modal** — only for multi-field config commands (``announce``,
  ``automod``, ``logsetup``) where labelled fields genuinely help.

Everything routes back through the dispatcher's ``dispatch()``, so the typed
path (``/bark warn @bob spamming``) and the enabled/permission gates all
still apply — the menu is just a friendlier front door.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import discord

logger = logging.getLogger("bark.interactions")

#: Multi-field config commands keep the form modal — they have 3+ structured
#: params (channel + title + message + color + image…) where labelled fields
#: genuinely beat a single packed reply. Everything else with params uses the
#: privacy-preserving reply-capture flow.
MODAL_ARG_COMMANDS: frozenset[str] = frozenset({"announce", "automod", "logsetup"})

#: How long to wait for the user's reply before giving up (seconds).
REPLY_CAPTURE_TIMEOUT = 90


def command_uses_modal(leaf) -> bool:
    """Whether ``leaf`` should collect args through a form modal.

    Only commands in :data:`MODAL_ARG_COMMANDS` (and only when they actually
    have parameters) get the modal; everything else with args is reply-capture.
    """
    if not getattr(leaf.command, "parameters", []):
        return False
    return leaf.path.split()[0] in MODAL_ARG_COMMANDS


def _param_summary(leaf) -> str:
    """Human "name (description)" summary of a command's parameters."""
    lines = []
    for p in leaf.command.parameters:
        name = (p.name or "value").replace("_", " ")
        desc = (getattr(p, "description", None) or "").strip()
        lines.append(f"• ``{name}`` — {desc}".rstrip())
    return "\n".join(lines) or "• no arguments"


# ── Reply capture (privacy-preserving arg collection) ──


class _FollowupResponseAdapter:
    """Mimic ``Interaction.response`` but route through ``followup``.

    The select interaction already responded (the ephemeral prompt), so the
    command callback can't call ``interaction.response.send_message`` again —
    discord.py raises ``InteractionResponded``. This adapter keeps command
    callbacks unchanged by forwarding ``send_message`` to ``followup.send``
    (ephemeral by default) and making ``defer`` a no-op, so the common
    ``defer``/``send``/``followup`` patterns all keep working.
    """

    def __init__(self, interaction, ephemeral: bool = True) -> None:
        self._interaction = interaction
        self._ephemeral = ephemeral

    async def send_message(self, content=None, **kwargs):
        kwargs.setdefault("ephemeral", self._ephemeral)
        return await self._interaction.followup.send(content=content, **kwargs)

    async def defer(self, *, ephemeral: bool = True) -> None:
        # Already responded (the prompt); nothing to defer.
        return None

    async def edit_message(self, **kwargs):
        return await self._interaction.edit_original_response(**kwargs)

    def is_done(self) -> bool:
        return True


class _ReplyArgsInteraction:
    """A proxy around the already-consumed select interaction.

    Lets the dispatcher and command callbacks respond after the ephemeral
    prompt was sent. ``response`` is swapped for :class:`_FollowupResponseAdapter`
    (so sends go through ``followup``); every other attribute/method delegates
    to the real interaction.
    """

    def __init__(self, real, ephemeral: bool = True) -> None:
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_ephemeral", ephemeral)

    @property
    def response(self):
        return _FollowupResponseAdapter(self._real, self._ephemeral)

    def __getattr__(self, name):
        return getattr(self._real, name)


async def _collect_args_by_reply(dispatcher, interaction, leaf) -> None:
    """Collect a command's args via an ephemeral prompt + captured reply.

    Privacy model: Bark posts an ephemeral prompt (only the invoker sees it),
    the user replies as a normal message, Bark reads the reply and **deletes
    it**, then dispatches the command. The sensitive reply never lingers, so
    the bot↔user exchange stays private and self-cleaning.
    """
    prompt = discord.Embed(
        title=f"Run {leaf.path}",
        description=(
            f"Reply with the value{'s' if len(list(leaf.command.parameters)) != 1 else ''} "
            f"for ``{leaf.path}`` below. Your reply is deleted after it's read."
        ),
        color=discord.Color.brand_green(),
    )
    prompt.add_field(name="Arguments", value=_param_summary(leaf), inline=False)
    prompt.set_footer(text="Type 'cancel' to abort. Times out after a while.")

    try:
        await interaction.response.send_message(embed=prompt, ephemeral=True)
    except discord.HTTPException:
        await interaction.followup.send(embed=prompt, ephemeral=True)

    client = getattr(interaction, "client", None) or getattr(dispatcher, "bot", None)
    if client is None or not hasattr(client, "wait_for"):
        try:
            await interaction.followup.send(
                "Couldn't start a reply listener — try the typed form instead.",
                ephemeral=True,
            )
        except discord.HTTPException:
            pass
        return
    channel_id = getattr(interaction, "channel_id", None) or getattr(
        getattr(interaction, "channel", None), "id", None
    )

    def check(m):
        return (
            m.author is not None
            and m.author.id == interaction.user.id
            and m.channel.id == channel_id
            and not m.author.bot
            and (m.content or "").strip() != ""
        )

    try:
        reply = await client.wait_for("message", check=check, timeout=REPLY_CAPTURE_TIMEOUT)
    except (asyncio.TimeoutError, AttributeError):
        try:
            await interaction.followup.send(
                "⏰ Timed out — run the command again if you still need it.",
                ephemeral=True,
            )
        except discord.HTTPException:
            pass
        return

    content = (reply.content or "").strip()
    # Privacy: delete the user's reply before acting on it.
    try:
        await reply.delete()
    except (discord.Forbidden, discord.HTTPException):
        pass

    if content.lower() in {"cancel", "cancel.", "abort"}:
        try:
            await interaction.followup.send("Cancelled.", ephemeral=True)
        except discord.HTTPException:
            pass
        return

    proxy = _ReplyArgsInteraction(interaction, ephemeral=True)
    try:
        await dispatcher.dispatch(proxy, leaf.path, content)
    except Exception:
        logger.exception("Reply-capture dispatch failed for %r", leaf.path)
        try:
            await interaction.followup.send("That command failed to run.", ephemeral=True)
        except Exception:
            pass


# ── Argument form modal ─────────────────────────────


class BarkArgsModal(discord.ui.Modal):
    """Collect a command's required arguments through a form.

    One labelled ``TextInput`` per required parameter (description as the
    placeholder). On submit the values are joined into an args string in
    parameter order and re-dispatched, so the typed-arg parsing and the
    permission/enabled gates in ``SlashDispatcher.dispatch`` all still run.
    """

    def __init__(self, dispatcher, leaf) -> None:
        self._dispatcher = dispatcher
        self._leaf = leaf
        title = f"Run {leaf.path}"[:45]
        super().__init__(title=title, timeout=300)
        self._inputs: dict[str, discord.ui.TextInput] = {}
        for p in leaf.command.parameters:
            label = (p.name or "value")[:45]
            placeholder = ((p.description or "") or p.name or "")[:100]
            field = discord.ui.TextInput(
                label=label,
                placeholder=placeholder,
                required=bool(getattr(p, "required", False)),
                min_length=1 if getattr(p, "required", False) else None,
                max_length=1024,
            )
            self._inputs[p.name] = field
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        values: list[str] = []
        for p in self._leaf.command.parameters:
            if p.name in self._inputs:
                values.append((self._inputs[p.name].value or "").strip())
        try:
            await self._dispatcher.dispatch(interaction, self._leaf.path, " ".join(values))
        except Exception:
            logger.exception("Form dispatch failed for %s", self._leaf.path)
            try:
                await interaction.response.send_message(
                    "That command failed to run.", ephemeral=True
                )
            except Exception:
                await interaction.followup.send(
                    "That command failed to run.", ephemeral=True
                )


# ── Command select (one module) ─────────────────────


class BarkCommandSelect(discord.ui.Select):
    """A select of a module's commands.

    Picking a command with required parameters opens a form modal (so the user
    fills labelled fields instead of typing slash args) for the multi-field
    config commands, or starts a privacy-preserving reply-capture prompt for
    everything else; a command without required params runs immediately
    through the dispatcher.
    """

    def __init__(
        self,
        dispatcher,
        leaves,
        placeholder: str = "Pick a command…",
    ) -> None:
        paths = [leaf.path.split() for leaf in leaves]
        shared_prefix = (
            paths[0][0]
            if paths and all(parts and parts[0] == paths[0][0] for parts in paths)
            else None
        )

        def action_label(leaf) -> str:
            parts = leaf.path.split()
            if shared_prefix and len(parts) > 1:
                parts = parts[1:]
            return " ".join(parts).replace("_", " ").title()[:100] or "Command"

        options = [
            discord.SelectOption(
                label=action_label(leaf),
                value=leaf.path,
                description=((getattr(leaf.command, "description", "") or "")[:100] or None),
            )
            for leaf in leaves[:25]
        ]
        if not options:
            options = [discord.SelectOption(label="No commands", value="_none")]
        super().__init__(placeholder=placeholder, options=options, min_values=1, max_values=1)
        self._dispatcher = dispatcher
        self._leaves = {leaf.path: leaf for leaf in leaves}

    async def callback(self, interaction: discord.Interaction) -> None:
        path = self.values[0]
        leaf = self._leaves.get(path)
        if leaf is None:
            return
        if getattr(leaf.command, "parameters", []):
            if command_uses_modal(leaf):
                await interaction.response.send_modal(BarkArgsModal(self._dispatcher, leaf))
            else:
                await _collect_args_by_reply(self._dispatcher, interaction, leaf)
            return
        try:
            await self._dispatcher.dispatch(interaction, path, "")
        except Exception:
            logger.exception("Command picker dispatch failed for %r", path)
            try:
                await interaction.response.send_message(
                    "That command failed to run.", ephemeral=True
                )
            except Exception:
                await interaction.followup.send(
                    "That command failed to run.", ephemeral=True
                )


class BackToModulesButton(discord.ui.Button):
    """Return from a module's command menu to the top-level module picker."""

    def __init__(self, dispatcher, guild_id) -> None:
        super().__init__(label="↩ Modules", style=discord.ButtonStyle.secondary)
        self._dispatcher = dispatcher
        self._guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        embed = self._dispatcher._build_overview_pages(self._guild_id)[0]  # noqa: SLF001
        view = module_menu_view(self._dispatcher, self._guild_id)
        await interaction.response.edit_message(embed=embed, view=view)


def command_menu_view(dispatcher, leaves, guild_id) -> discord.ui.View:
    """A view: this module's command select + a back-to-modules button."""
    view = discord.ui.View(timeout=300)
    view.add_item(BarkCommandSelect(dispatcher, leaves))
    view.add_item(BackToModulesButton(dispatcher, guild_id))
    return view


# ── Module select (top level) ───────────────────────


class BarkModuleSelect(discord.ui.Select):
    """Top-level menu: one option per enabled module.

    Picking a module edits the message to that module's command menu.
    """

    def __init__(self, dispatcher, modules: list[tuple[str, list]], guild_id) -> None:
        options = [
            discord.SelectOption(
                label=module_name.replace("_", " ").title()[:100],
                value=module_name,
                description=f"{len(paths)} command{'s' if len(paths) != 1 else ''}",
            )
            for module_name, paths in modules[:25]
        ]
        if not options:
            options = [discord.SelectOption(label="No modules", value="_none")]
        super().__init__(placeholder="Pick a module…", options=options, min_values=1, max_values=1)
        self._dispatcher = dispatcher
        self._modules = dict(modules)
        self._guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        module_name = self.values[0]
        paths = self._modules.get(module_name, [])
        leaves = [
            self._dispatcher._registry[p] for p in paths  # noqa: SLF001
            if self._dispatcher._path_enabled(self._guild_id, self._dispatcher._registry[p])  # noqa: SLF001
        ]
        pages = self._dispatcher._build_menu_pages(  # noqa: SLF001
            leaves,
            title=f"🐺 {module_name.replace('_', ' ').title()}",
            detail="Choose a command below. If it needs details, Bark asks you in a private message.",
        )
        view = command_menu_view(self._dispatcher, leaves, self._guild_id)
        await interaction.response.edit_message(embed=pages[0], view=view)


def module_menu_view(dispatcher, guild_id) -> discord.ui.View:
    """Top-level menu: pick a module to drill into its commands."""
    modules: list[tuple[str, list]] = []
    for module_name, paths in sorted(dispatcher._module_paths.items()):  # noqa: SLF001
        enabled = [
            p for p in paths
            if dispatcher._path_enabled(guild_id, dispatcher._registry[p])  # noqa: SLF001
        ]
        if enabled:
            modules.append((module_name, enabled))
    view = discord.ui.View(timeout=300)
    view.add_item(BarkModuleSelect(dispatcher, modules, guild_id))
    return view


# ── Legacy flat picker (kept for the help module) ────


class BarkLegacySelect(discord.ui.Select):
    """The original flat command picker (all paths in one select)."""

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
    """A view carrying the legacy command-select menu."""

    def __init__(self, dispatch, paths: list[str], *, timeout: float = 300.0) -> None:
        super().__init__(timeout=timeout)
        self.add_item(BarkLegacySelect(dispatch, paths))


def command_picker_view(dispatcher, paths: list[str]) -> BarkActionView:
    """A select-menu view that runs any of the given command paths via dispatcher."""

    def _dispatch(interaction: discord.Interaction, command: str, args: str) -> Any:
        return dispatcher.dispatch(interaction, command, args)

    return BarkActionView(_dispatch, paths)


def attach_command_picker(
    dispatcher,
    paths: list[str] | None = None,
) -> BarkActionView:
    """Build a view whose select re-runs a command via the dispatcher."""
    if paths is None:
        paths = sorted(dispatcher._registry.keys())  # noqa: SLF001
    return command_picker_view(dispatcher, paths)
