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

from services.interactions import command_picker_view

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
        self._module_paths: dict[str, list[str]] = {}  # module name -> command paths
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
        self._module_paths.setdefault(module_name, []).append(path)

    def unregister_module(self, module_name: str) -> None:
        """Drop every path contributed by a module."""
        for path in [p for p, leaf in self._registry.items() if leaf.module_name == module_name]:
            del self._registry[path]
        self._module_paths.pop(module_name, None)

    # ── Command build ─────────────────────────────────

    def build_command(self, group_name: str) -> app_commands.Command:
        """Construct the single top-level ``/<group_name>`` app command.

        Options are auto-derived from the callback signature: ``command``
        (optional string, autocompleted) and ``args`` (optional string). Making
        ``command`` optional lets a bare ``/bark`` show guidance.
        """
        async def _callback(
            interaction: discord.Interaction, command: str = "", args: str = ""
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
        path = (command or "").strip().lower()
        guild_id = getattr(interaction, "guild_id", None)

        # 1. Bare /bark -> top-level overview so users always get guidance.
        if not path:
            await self._show_overview(interaction, guild_id)
            return

        # 2. Exact leaf (e.g. "announce") -> run it, or show usage if it needs
        #    required args the user hasn't supplied.
        leaf = self._registry.get(path)
        if leaf is None:
            matches = [p for p in self._registry if p.startswith(path)]
            if len(matches) == 1:
                path, leaf = matches[0], self._registry[matches[0]]
        if leaf is not None:
            await self._invoke_leaf(interaction, leaf, args)
            return

        # 3. A module/category name (e.g. "moderation") -> menu of its commands.
        if path in self._module_paths:
            await self._show_module_menu(interaction, path, guild_id)
            return

        # 4. A group prefix (e.g. "trivia" for "trivia start") -> submenu.
        group = [p for p in self._registry if p.startswith(path + " ")]
        if group:
            await self._show_menu(
                interaction,
                title=f"🐺 {path.title()} commands",
                paths=group,
                guild_id=guild_id,
                detail=(
                    "Add the subcommand to complete it, e.g. "
                    f"`/{self._cmd.name if self._cmd else 'bark'} {group[0]}`."
                ),
            )
            return

        # 5. Nothing resolved -> guidance.
        await self._show_unknown(interaction, path)

    async def _invoke_leaf(self, interaction: discord.Interaction, leaf: Leaf, args: str) -> None:
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
                logger.exception("Enablement check failed for command %s", leaf.path)
        # Show usage if a required arg is missing, instead of acting on a
        # default (e.g. warning the invoker because no target was given).
        if _missing_required_arg(leaf.command, args):
            await self._show_usage(interaction, leaf)
            return
        kwargs = await parse_args_to_kwargs(interaction, leaf.command, args)
        await leaf.command.callback(interaction, **kwargs)

    # ── Guidance / menus ──────────────────────────────

    def _group_name(self) -> str:
        return self._cmd.name if self._cmd else "bark"

    def _usage_line(self, leaf: Leaf) -> str:
        params = " ".join(f"<{p.name}>" for p in leaf.command.parameters)
        return f"/{self._group_name()} {leaf.path} {params}".strip()

    def _usage_desc(self, leaf: Leaf) -> str:
        desc = getattr(leaf.command, "description", "") or ""
        params = " ".join(f"<{p.name}>" for p in leaf.command.parameters)
        line = f"`/{self._group_name()} {leaf.path}" + (f" {params}`" if params else "`")
        return f"{line} — {desc}" if desc else line

    async def _show_usage(self, interaction: discord.Interaction, leaf: Leaf) -> None:
        embed = discord.Embed(
            title=f"🐺 {leaf.path.title()}",
            description=self._usage_desc(leaf),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="How to use",
            value=f"Type `{self._usage_line(leaf)}`.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _show_unknown(self, interaction: discord.Interaction, path: str) -> None:
        embed = discord.Embed(
            title="🤔 That command isn't recognised",
            description=(
                f"`{path or '<none>'}` isn't a command. Type `/{self._group_name()}` and "
                "pick one from the autocomplete list, or run `help`."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Tip",
            value=(
                f"Typing `/{self._group_name()} <module>` (e.g. `moderation`) shows every "
                "command in that module."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _show_module_menu(
        self, interaction: discord.Interaction, module_name: str, guild_id
    ) -> None:
        paths = self._module_paths.get(module_name, [])
        await self._show_menu(
            interaction,
            title=f"🐺 {module_name.title()} commands",
            paths=paths,
            guild_id=guild_id,
            detail=(
                f"`/{self._group_name()} <command> [args...]` — pick a command below or "
                "type it after the slash command."
            ),
        )

    async def _show_menu(
        self, interaction: discord.Interaction, title: str, paths: list[str],
        guild_id, detail: str = "",
    ) -> None:
        enabled = [
            p for p in paths
            if self._path_enabled(guild_id, self._registry[p])
        ]
        embed = discord.Embed(title=title, color=discord.Color.blurple())
        if detail:
            embed.description = detail
        if enabled:
            for p in sorted(enabled):
                embed.add_field(
                    name=f"/{self._group_name()} {p}",
                    value=self._registry[p].command.description or "—",
                    inline=False,
                )
        else:
            embed.description = "No commands in this module are enabled for this server."
        view = None
        if enabled:
            view = command_picker_view(dispatcher=self, paths=enabled)
        if view is not None:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _show_overview(self, interaction: discord.Interaction, guild_id) -> None:
        enabled = sorted(p for p in self._registry if self._path_enabled(guild_id, self._registry[p]))
        embed = discord.Embed(
            title=f"🐺 {self._group_name().title()} — how to use",
            description=(
                "Commands run through a single slash command. Type `/"
                f"{self._group_name()} <command> [args...]` (or pick a command from the "
                "autocomplete), and you'll get an interactive response."
            ),
            color=discord.Color.blurple(),
        )
        # Group by module for a scannable overview.
        by_module: dict[str, list[str]] = {}
        for p in enabled:
            by_module.setdefault(self._registry[p].module_name, []).append(p)
        for module_name, paths in sorted(by_module.items()):
            sample = ", ".join(f"`{p}`" for p in sorted(paths)[:4])
            more = f" +{len(paths) - 4} more" if len(paths) > 4 else ""
            embed.add_field(
                name=module_name.title(),
                value=f"{sample}{more}",
                inline=False,
            )
        view = command_picker_view(dispatcher=self, paths=enabled)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

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


def _missing_required_arg(command, args: str) -> bool:
    """True when the leaf has required params but ``args`` supplies too few tokens.

    Used to show usage guidance instead of running a command against defaults
    (e.g. warning the invoker because no target member was given).
    """
    required = [
        p for p in getattr(command, "parameters", [])
        if getattr(p, "required", False)
    ]
    if not required:
        return False
    supplied = len((args or "").split())
    return supplied < len(required)
