"""Single ``/bark`` dispatcher — one slash command, unlimited module commands.

Discord caps a command group at 25 subcommands and a bot at 100 global
commands. To keep native slash commands while letting Bark scale to any number
of modules and add-on plugins, this registers exactly ONE top-level app
command::

    /bark <command> [args...]

``command`` is a string option with autocomplete that lists every module +
plugin command path (``help``, ``warn``, ``trivia start``, ``birthday
channel`` …). ``args`` is a free-form string parsed into the leaf handler's
typed parameters. This sidesteps both the subcommand-group cap and the global
command cap entirely.

Module handlers are ``discord.app_commands.Command`` objects (the same ones the
prefix adapter used); the dispatcher invokes their ``callback`` with the real
``discord.Interaction``, so no module business logic is rewritten.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

import discord
from discord import app_commands

if TYPE_CHECKING:
    from modules.base import BarkModule

logger = logging.getLogger("bark.slash_dispatcher")

AUTOCOMPLETE_LIMIT = 25


@dataclass
class Leaf:
    """A dispatchable module command: the app-command leaf + enablement gate."""

    command: Any  # discord.app_commands.Command
    check: Callable[[Any], Any] | None = None
    path: str = ""
    module_name: str = ""


class SlashDispatcher:
    """Builds and dispatches the single ``/bark`` command from module commands."""

    def __init__(self, bot, module_manager) -> None:
        self.bot = bot
        self.manager = module_manager
        self._registry: dict[str, Leaf] = {}
        self._cmd: app_commands.Command | None = None

    # ── Registration ──────────────────────────────────

    def register_module(self, module_name: str, module: BarkModule) -> None:
        """Index every slash-capable command a module exposes."""
        check = self.manager._command_enabled_check(module_name)  # noqa: SLF001
        for cmd in module.get_commands():
            if not cmd.slash:
                continue
            factory = getattr(module, f"_make_{cmd.name}_command", None)
            if not factory:
                continue
            try:
                root = factory()
            except Exception:
                logger.exception(
                    "Failed to build command '%s' for module '%s'", cmd.name, module_name
                )
                continue
            self._add_leaf(module_name, root, check)

    def _add_leaf(self, module_name: str, cmd, check, prefix: str = "") -> None:
        children = getattr(cmd, "commands", None)
        if children:  # it's a Group -> recurse into subcommands
            base = f"{prefix}{cmd.name} " if getattr(cmd, "name", None) else prefix
            for sub in children:
                self._add_leaf(module_name, sub, check, base)
            return
        path = f"{prefix}{getattr(cmd, 'name', '')}".strip()
        if not path:
            return
        # Keep paths collision-free across modules/plugins.
        if path in self._registry:
            path = f"{module_name} {path}".strip()
        self._registry[path] = Leaf(command=cmd, check=check, path=path, module_name=module_name)

    def unregister_module(self, module_name: str) -> None:
        """Drop every path contributed by a module."""
        for path in [p for p, leaf in self._registry.items() if leaf.module_name == module_name]:
            del self._registry[path]

    # ── Command build ─────────────────────────────────

    def build_command(self, group_name: str) -> app_commands.Command:
        """Construct the single top-level ``/<group_name>`` app command.

        Options are auto-derived from the callback signature: ``command``
        (required string, autocompleted) and ``args`` (optional string).
        """
        async def _callback(
            interaction: discord.Interaction, command: str, args: str = ""
        ) -> None:
            await self.dispatch(interaction, command, args)

        cmd = app_commands.Command(
            name=group_name,
            description="Bark commands — pick a command (tab to autocomplete) and add optional args.",
            callback=_callback,
        )
        cmd.autocomplete("command")(self._autocomplete)
        self._cmd = cmd
        return cmd

    # ── Dispatch ──────────────────────────────────────

    async def dispatch(self, interaction: discord.Interaction, command: str, args: str = "") -> None:
        path = (command or "").strip()
        leaf = self._registry.get(path)
        if leaf is None:
            matches = [p for p in self._registry if p.startswith(path)] if path else []
            if len(matches) == 1:
                path, leaf = matches[0], self._registry[matches[0]]
        if leaf is None:
            await interaction.response.send_message(
                f"Unknown command `{path or '<none>'}`. Type `/{self._cmd.name if self._cmd else 'bark'}` "
                "and pick one from the autocomplete list.",
                ephemeral=True,
            )
            return
        if leaf.check is not None:
            try:
                if not await leaf.check(interaction):
                    await interaction.response.send_message(
                        "This module isn't enabled for this server — turn it on in the "
                        "dashboard **Modules** page.",
                        ephemeral=True,
                    )
                    return
            except Exception:
                logger.exception("Enablement check failed for command %s", path)
        kwargs = await parse_args_to_kwargs(interaction, leaf.command, args)
        await leaf.command.callback(interaction, **kwargs)

    # ── Autocomplete ──────────────────────────────────

    async def _autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        current = (current or "").lower()
        guild_id = getattr(interaction, "guild_id", None)
        paths = [
            path
            for path, leaf in self._registry.items()
            if (not current or current in path.lower())
            and self._path_enabled(guild_id, leaf)
        ]
        paths.sort()
        return [app_commands.Choice(name=path, value=path) for path in paths[:AUTOCOMPLETE_LIMIT]]

    def _path_enabled(self, guild_id, leaf: Leaf) -> bool:
        if guild_id is None:
            return True
        try:
            return self.manager.is_enabled_for_guild(guild_id, leaf.module_name)
        except Exception:
            return True


# ── Parameter / arg parsing helpers ──────────────────


async def parse_args_to_kwargs(
    interaction: discord.Interaction, command, args: str
) -> dict[str, Any]:
    """Parse the free-form ``args`` string into the leaf's typed parameters.

    Reuses the same token→type conversion the prefix adapter used, but resolves
    mentions/roles/channels against the interaction's guild instead of a text
    command context.
    """
    params = list(getattr(command, "parameters", []))
    tokens = (args or "").split()
    kwargs: dict[str, Any] = {}
    for param in params:
        t = param.type
        if t is discord.AppCommandOptionType.string:
            kwargs[param.name] = tokens.pop(0) if tokens else ""
        elif t is discord.AppCommandOptionType.number:
            try:
                kwargs[param.name] = float(tokens.pop(0)) if tokens else 0.0
            except (TypeError, ValueError):
                kwargs[param.name] = 0.0
        elif t is discord.AppCommandOptionType.integer:
            try:
                kwargs[param.name] = int(tokens.pop(0)) if tokens else 0
            except (TypeError, ValueError):
                kwargs[param.name] = 0
        elif t is discord.AppCommandOptionType.boolean:
            raw = tokens.pop(0) if tokens else ""
            kwargs[param.name] = raw.strip().lower() in ("true", "1", "yes", "on", "y", "enabled")
        elif t in (discord.AppCommandOptionType.user, discord.AppCommandOptionType.mentionable):
            kwargs[param.name] = await _resolve_member(interaction, tokens.pop(0)) if tokens else interaction.user
        elif t is discord.AppCommandOptionType.role:
            kwargs[param.name] = await _resolve_role(interaction, tokens.pop(0)) if tokens else None
        elif t is discord.AppCommandOptionType.channel:
            kwargs[param.name] = await _resolve_channel(interaction, tokens.pop(0)) if tokens else None
    return kwargs


async def _resolve_member(interaction, raw: str):
    guild = getattr(interaction, "guild", None)
    if guild is None:
        return interaction.user
    raw = raw.strip()
    target_id = _extract_id(raw, "<@", ">")
    if target_id is None:
        target_id = raw
    try:
        member = guild.get_member(int(target_id)) or await guild.fetch_member(int(target_id))
        if member is not None:
            return member
    except Exception:
        pass
    for m in guild.members:
        if m.name == raw or m.display_name == raw or str(m.id) == raw:
            return m
    return interaction.user


async def _resolve_role(interaction, raw: str):
    guild = getattr(interaction, "guild", None)
    if guild is None:
        return None
    target_id = _extract_id(raw, "<@&", ">")
    if target_id is not None:
        return guild.get_role(int(target_id))
    for role in guild.roles:
        if role.name == raw or str(role.id) == raw:
            return role
    return None


async def _resolve_channel(interaction, raw: str):
    guild = getattr(interaction, "guild", None)
    if guild is None:
        return None
    target_id = _extract_id(raw, "<#", ">")
    if target_id is not None:
        return guild.get_channel(int(target_id))
    for ch in guild.channels:
        if ch.name == raw or str(ch.id) == raw:
            return ch
    return None


def _extract_id(raw: str, start: str, end: str) -> int | None:
    if raw.startswith(start) and end in raw:
        inner = raw.split(start, 1)[1].split(end, 1)[0]
        try:
            return int(inner)
        except ValueError:
            return None
    return None
