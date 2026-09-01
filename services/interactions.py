"""Interactive response helpers for slash commands.

Bark's flat ``/bark`` dispatcher is the single registered command; this module
makes it feel native by responding with an interactive menu instead of making
the user type ``command``/``args``:

    /bark                     -> overview embed + a MODULE select menu
    pick a module             -> that module's commands as a COMMAND select
    pick a command w/o args   -> runs immediately
    pick a command w/ args    -> a form MODAL collects the arguments

Everything routes back through the dispatcher's ``dispatch()``, so the typed
path (``/bark warn @bob spamming``) and the enabled/permission gates all
still apply — the menu is just a friendlier front door.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import discord

logger = logging.getLogger("bark.interactions")


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
    fills labelled fields instead of typing slash args); a command without
    required params runs immediately through the dispatcher.
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
            await interaction.response.send_modal(BarkArgsModal(self._dispatcher, leaf))
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
            detail="Choose a command below. If it needs details, Bark opens a short form.",
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
