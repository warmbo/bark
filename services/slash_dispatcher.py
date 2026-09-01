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

# Alias names for modules and commands so users can type short forms, e.g.
# `/bark rep lb` instead of `/bark reputation leaderboard`. Keys are canonical
# names; values are alternate names registered alongside (sharing the same
# callback). Module aliases create an extra subgroup; command aliases create
# extra subcommands within that module's subgroup (or directly off /bark for
# single-command modules). Discord has no native alias concept, so we register
# duplicate entries pointing at the same underlying command.
MODULE_ALIASES: dict[str, tuple[str, ...]] = {
    "reputation": ("rep",),
    "moderation": ("mod",),
    "role_manager": ("role",),
    "logging": ("log",),
    "auto_voice": ("voice", "av"),
    "announcements": ("announce",),
    "birthdays": ("bday", "birthday"),
}

COMMAND_ALIASES: dict[str, tuple[str, ...]] = {
    "leaderboard": ("lb", "top"),
    "reputation": ("rep", "score"),
    "thanks": ("thx", "ty"),
    "warn": ("w",),
    "warnings": ("warns", "warnlist"),
    "cases": ("c",),
    "clearwarn": ("cw",),
    "voice_sessions": ("vs", "sessions"),
    "vc_kick": ("vk",),
    "vc_move": ("vm",),
    "vc_mute": ("vmu",),
    "vc_unmute": ("vum",),
    "vc_deafen": ("vdef",),
    "vc_undeafen": ("vundef",),
    "automod": ("am",),
    "logsetup": ("logs", "setup"),
    "logstatus": ("status",),
    "logfiles": ("lf",),
    "voice_name": ("vn",),
    "voice_limit": ("vl",),
    "voice_lock": ("vlock",),
    "voice_unlock": ("vunlock",),
    "welcome": ("hello",),
    "speak": ("say",),
}


@dataclass
class Leaf:
    """A dispatchable module command: the app-command leaf + enablement gate."""

    command: Any  # discord.app_commands.Command
    check: Callable[[Any], Any] | None = None
    path: str = ""
    module_name: str = ""


class SlashDispatcher:
    """Builds and dispatches the single ``/bark`` command from module commands."""

    # Discord hard cap: a subcommand group may hold at most 25 children. A
    # command-heavy module (moderation) with aliases would exceed it and fail
    # the entire tree sync with 50035 — alias leaves are dropped past this.
    MAX_GROUP_CHILDREN = 25

    def __init__(self, bot, module_manager) -> None:
        self.bot = bot
        self.manager = module_manager
        self._registry: dict[str, Leaf] = {}
        self._module_paths: dict[str, list[str]] = {}  # module name -> command paths
        self._cmd: app_commands.Command | None = None
        self._group: app_commands.Group | None = None

    # ── Registration ──────────────────────────────────

    def register_module(self, module_name: str, module: BarkModule) -> None:
        """Index every slash-capable command a module exposes."""
        check = self.manager._command_enabled_check(module_name)  # noqa: SLF001
        registered_any = False
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
            registered_any = True
        if self._group is not None and registered_any:
            self._sync_module_to_group(module_name)

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

    # ── Native subcommand-group build ─────────────────

    def build_group(self, group_name: str) -> app_commands.Group:
        """Construct ``/<group_name>`` as a native command Group.

        Multi-command modules become subcommand-groups (``/bark moderation
        warn``); single-command modules and the general help commands hang
        directly off the root (``/bark welcome``, ``/bark stats``). Every leaf
        carries a check that gates on its module being enabled for the guild.
        Native subcommands give Discord typed-argument autocomplete, so users
        type ``/bark reputation leaderboard`` instead of selecting the old
        ``command``/``args`` string fields.
        """
        root = app_commands.Group(
            name=group_name,
            description="Bark commands — pick a module or command.",
        )
        for module_name in sorted(self._module_paths):
            self._add_module_to_group(root, module_name)
        self._group = root
        return root

    def _add_module_to_group(self, root: app_commands.Group, module_name: str) -> None:
        """Add one module's leaves to a group (idempotent per module)."""
        leaves = [self._registry[p] for p in self._module_paths[module_name]]
        if not leaves:
            return
        if len(leaves) == 1 or module_name == "help":
            for leaf in leaves:
                try:
                    root.add_command(self._native_leaf(leaf))
                    for alias in self._command_aliases(leaf):
                        try:
                            root.add_command(self._alias_leaf(leaf, alias))
                        except Exception:
                            logger.exception(
                                "Failed to add alias %s for %s to group", alias, leaf.path
                            )
                except Exception:
                    logger.exception("Failed to add %s to group", leaf.path)
        else:
            sub = app_commands.Group(
                name=module_name,
                description=(module_name.title() + " commands")[:100],
            )
            for leaf in leaves:
                if len(sub.commands) >= self.MAX_GROUP_CHILDREN:
                    break
                try:
                    sub.add_command(self._native_leaf(leaf))
                    for alias in self._command_aliases(leaf):
                        # Discord caps a subcommand group at 25 children; a
                        # command-heavy module (e.g. moderation) can exceed it
                        # once aliases are included, which fails the whole tree
                        # sync with 50035. Aliases are convenience — drop the
                        # ones that would overflow instead of losing the
                        # canonical command (2026-09-01 tree-sync incident).
                        if len(sub.commands) >= self.MAX_GROUP_CHILDREN:
                            break
                        try:
                            sub.add_command(self._alias_leaf(leaf, alias))
                        except Exception:
                            logger.exception(
                                "Failed to add alias %s for %s", alias, leaf.path
                            )
                except Exception:
                    logger.exception("Failed to add %s to group %s", leaf.path, module_name)
            try:
                root.add_command(sub)
                for mod_alias in MODULE_ALIASES.get(module_name, ()):
                    if mod_alias == module_name:
                        continue
                    alias_sub = app_commands.Group(
                        name=mod_alias,
                        description=(module_name.title() + " commands")[:100],
                    )
                    for leaf in leaves:
                        if len(alias_sub.commands) >= self.MAX_GROUP_CHILDREN:
                            break
                        try:
                            alias_sub.add_command(self._native_leaf(leaf))
                            for alias in self._command_aliases(leaf):
                                if len(alias_sub.commands) >= self.MAX_GROUP_CHILDREN:
                                    break
                                try:
                                    alias_sub.add_command(self._alias_leaf(leaf, alias))
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    try:
                        root.add_command(alias_sub)
                    except Exception:
                        logger.exception("Failed to add module alias group %s", mod_alias)
            except Exception:
                logger.exception("Failed to add module group %s", module_name)

    def _command_aliases(self, leaf: Leaf) -> tuple[str, ...]:
        """Return the command aliases for a leaf (canonical name only, no collision)."""
        name = getattr(leaf.command, "name", "")
        aliases = COMMAND_ALIASES.get(name, ())
        # Skip aliases that would collide with an existing canonical path.
        return tuple(a for a in aliases if a != name and a not in self._registry)

    def _alias_leaf(self, leaf: Leaf, alias: str) -> Any:
        """Return an alias Command sharing the leaf's callback + check.

        discord.py requires a distinct Command object per name, but a shared
        callback means invoking the alias runs exactly the same handler with the
        same parameters and the same module enablement check.
        """
        orig = leaf.command
        alias_cmd = app_commands.Command(
            name=alias,
            description=getattr(orig, "description", "") or "",
            callback=orig.callback,
        )
        # Mirror the module enablement check added by _native_leaf.
        try:
            for check in getattr(orig, "checks", []):
                alias_cmd.add_check(check)
        except Exception:
            logger.exception("Failed to copy checks to alias %s", alias)
        return alias_cmd

    def _sync_module_to_group(self, module_name: str) -> None:
        """Add (or refresh) a module's commands in the live group tree."""
        if self._group is None:
            return
        # Remove any existing child for this module (by subgroup name or by the
        # direct leaf names) so re-registration is idempotent.
        for child in list(self._group.commands):
            child_name = getattr(child, "name", "")
            if child_name == module_name:
                try:
                    self._group.remove_command(module_name)
                except Exception:
                    pass
        self._add_module_to_group(self._group, module_name)

    def _native_leaf(self, leaf: Leaf) -> Any:
        """Return a leaf command wired for native subcommand invocation.

        The leaf is a real ``app_commands.Command`` (or Group). We add a check
        that raises ``CheckFailure`` when its module is disabled for the guild,
        so Discord's native UI enforces the module gate. ``default_permissions``
        on the leaf are enforced natively by Discord.
        """
        cmd = leaf.command
        module_name = leaf.module_name

        async def _module_gate(interaction: discord.Interaction) -> bool:
            guild_id = getattr(interaction, "guild_id", None)
            if guild_id is None:
                return True  # DM / no-guild context — never gate here
            try:
                enabled = self.manager.is_enabled_for_guild(guild_id, module_name)
            except Exception:
                logger.exception("Enablement check failed for module %s", module_name)
                enabled = False  # fail closed
            if not enabled:
                raise discord.app_commands.CheckFailure(
                    f"module '{module_name}' is not enabled here"
                )
            return True

        try:
            cmd.add_check(_module_gate)
        except Exception:
            logger.exception("Failed to add enablement check to %s", leaf.path)
        return cmd

    # ── Dispatch ──────────────────────────────────────

    async def dispatch(self, interaction: discord.Interaction, command: str, args: str = "") -> None:
        path = (command or "").strip().lower()
        guild_id = getattr(interaction, "guild_id", None)

        # 1. Bare /bark -> top-level overview so users always get guidance.
        if not path:
            await self._show_overview(interaction, guild_id)
            return

        # 1b. /bark help <command> -> detailed help for a specific command.
        if path == "help" and (args or "").strip():
            target = (args or "").strip().split()[0]
            await self._show_help_for(interaction, target)
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
        # Authorize the invoker. Every command runs through this dispatcher,
        # but the leaf app-commands are never added to the tree (only the
        # single top-level command is), so Discord never enforces their
        # @default_permissions. Re-apply the declared requirement here against
        # the invoker's guild permissions — this is the ONLY server-side gate
        # that keeps a plain member from running /bark ban @Owner.
        required = leaf.command.default_permissions
        if required is not None:
            member = getattr(interaction, "user", None)
            user_perms = getattr(member, "guild_permissions", None)
            if user_perms is None or not (user_perms >= required):
                await interaction.response.send_message(
                    "❌ You don't have permission to use this command here.",
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
                logger.exception("Enablement check failed for command %s", leaf.path)
        # Show usage if a required arg is missing, instead of acting on a
        # default (e.g. warning the invoker because no target was given).
        if _missing_required_arg(leaf.command, args):
            await self._show_usage(interaction, leaf)
            return
        kwargs = await parse_args_to_kwargs(interaction, leaf.command, args)
        unresolved = _unresolved_required_target(leaf.command, kwargs)
        if unresolved is not None:
            # A required member/role/channel didn't resolve (mistyped mention or
            # stale id). Fail clearly instead of acting on a default target.
            await interaction.response.send_message(
                f"Couldn't find that {unresolved} — check the mention or ID and try again.",
                ephemeral=True,
            )
            return
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

    def _param_lines(self, leaf: Leaf) -> list[str]:
        """One line per parameter: `<name> — description (required|optional)`."""
        lines = []
        for p in leaf.command.parameters:
            req = "required" if getattr(p, "required", False) else "optional"
            desc = getattr(p, "description", "") or ""
            lines.append(f"`<{p.name}>` — {desc} *({req})*".rstrip() if desc else f"`<{p.name}>` *({req})*")
        return lines

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
        if leaf.command.parameters:
            embed.add_field(
                name="Arguments",
                value="\n".join(self._param_lines(leaf)),
                inline=False,
            )
        embed.add_field(
            name="Need more?",
            value=f"Run `/{self._group_name()} help {leaf.path}` for the full breakdown.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _show_help_for(self, interaction: discord.Interaction, target: str) -> None:
        """Detailed help for one command: params, descriptions, usage."""
        target = (target or "").strip().lower()
        leaf = self._registry.get(target)
        if leaf is None:
            # Maybe a module/group -> point at its menu.
            if target in self._module_paths:
                await self._show_module_menu(interaction, target, getattr(interaction, "guild_id", None))
                return
            matches = [p for p in self._registry if p.startswith(target)]
            if len(matches) == 1:
                leaf = self._registry[matches[0]]
            else:
                await self._show_unknown(interaction, target)
                return
        embed = discord.Embed(
            title=f"🐺 {leaf.path} — command help",
            color=discord.Color.blurple(),
        )
        embed.description = (
            f"{getattr(leaf.command, 'description', '') or ''}\n\n"
            f"**Usage:** `{self._usage_line(leaf)}`"
        )
        if leaf.command.parameters:
            embed.add_field(
                name="Arguments",
                value="\n".join(self._param_lines(leaf)),
                inline=False,
            )
        embed.add_field(
            name="Module",
            value=leaf.module_name.title(),
            inline=True,
        )
        embed.set_footer(text=f"Part of {self._group_name()}")
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

    def _command_line(self, leaf: Leaf) -> str:
        """A single menu item: `/bark <path> <params> — description`."""
        params = " ".join(f"<{p.name}>" for p in leaf.command.parameters)
        usage = f"/{self._group_name()} {leaf.path}" + (f" {params}" if params else "")
        desc = getattr(leaf.command, "description", "") or ""
        return f"`{usage}` — {desc}" if desc else f"`{usage}`"

    def _enabled_leaves(self, guild_id) -> list[Leaf]:
        return [
            leaf for _, leaf in sorted(self._registry.items())
            if self._path_enabled(guild_id, leaf)
        ]

    def _chunk_by_module(
        self, leaves: list[Leaf], max_fields: int = 6, max_chars: int = 1000
    ) -> list[list[tuple[str, list[Leaf]]]]:
        """Group leaves by module into page-chunks of at most ``max_fields``
        fields AND at most ``max_chars`` rendered characters per field.

        Discord rejects any embed field whose value exceeds 1024 chars
        (error 50035), so a single command-heavy module must split across
        pages instead of emitting one oversized field (2026-08-24 incident:
        Moderation's joined lines hit exactly 1025).
        """
        by_module: dict[str, list[Leaf]] = {}
        for leaf in leaves:
            by_module.setdefault(leaf.module_name, []).append(leaf)

        def render(ls: list[Leaf]) -> str:
            return "\n".join(self._command_line(leaf) for leaf in ls)

        pages: list[list[tuple[str, list[Leaf]]]] = []
        current: list[tuple[str, list[Leaf]]] = []
        for module_name in sorted(by_module):
            ls = sorted(by_module[module_name], key=lambda leaf: leaf.path)
            # A single command-heavy module can exceed the embed-field cap on
            # its own — split it into sub-groups that each render under limit.
            for group in self._split_by_char_limit(ls, lambda g: len(render(g)), max_chars):
                if current and len(current) >= max_fields:
                    pages.append(current)
                    current = []
                current.append((module_name, group))
        if current:
            pages.append(current)
        return pages

    @staticmethod
    def _split_by_char_limit(ls: list[Leaf], length_of, limit: int) -> list[list[Leaf]]:
        """Split ``ls`` into consecutive groups whose rendered length stays
        under ``limit``. A single item longer than the limit becomes its own
        group (nothing more we can do without truncating its text)."""
        groups: list[list[Leaf]] = []
        group: list[Leaf] = []
        for leaf in ls:
            candidate = [*group, leaf]
            if group and length_of(candidate) > limit:
                groups.append(group)
                group = [leaf]
            else:
                group = candidate
        if group:
            groups.append(group)
        return groups

    @staticmethod
    def _set_footers(pages: list[discord.Embed]) -> None:
        total = len(pages)
        for i, embed in enumerate(pages):
            if total > 1:
                embed.set_footer(text=f"Page {i + 1}/{total} — react ◀ ▶ to navigate")
            else:
                embed.set_footer(text="React ◀ ▶ to page through the rest")

    def _build_overview_pages(self, guild_id) -> list[discord.Embed]:
        enabled = self._enabled_leaves(guild_id)
        core = [leaf for leaf in enabled if not self.manager.is_plugin(leaf.module_name)]
        plugins = [leaf for leaf in enabled if self.manager.is_plugin(leaf.module_name)]

        how_to = (
            "Bark commands run through a single slash command. Type "
            f"`/{self._group_name()} <command> [args...]`, or type a module name "
            f"(e.g. `{self._group_name()} moderation`) for its menu. For details "
            f"on any command, use `/{self._group_name()} help <command>`.\n\n"
            "Info commands (help, info, leaderboard, reputation…) are private "
            "by default — post them for everyone by adding `public` as the last "
            f"argument, e.g. `/{self._group_name()} leaderboard public`."
        )
        pages: list[discord.Embed] = []
        core_chunks = self._chunk_by_module(core)
        for i, chunk in enumerate(core_chunks):
            embed = discord.Embed(
                title="🐺 Bark — how to use" if i == 0 else "🐺 Bark commands",
                color=discord.Color.blurple(),
            )
            if i == 0:
                embed.description = how_to
            for module_name, ls in chunk:
                embed.add_field(
                    name=module_name.title(),
                    value="\n".join(self._command_line(leaf) for leaf in ls),
                    inline=False,
                )
            pages.append(embed)
        if plugins:
            for chunk in self._chunk_by_module(plugins):
                embed = discord.Embed(
                    title="🧩 Add-on Modules",
                    description="Commands from installed add-on plugins.",
                    color=discord.Color.blurple(),
                )
                for module_name, ls in chunk:
                    embed.add_field(
                        name=module_name.title(),
                        value="\n".join(self._command_line(leaf) for leaf in ls),
                        inline=False,
                    )
                pages.append(embed)
        if not pages:
            pages = [discord.Embed(title="🐺 Bark", description="No commands available yet.")]
        self._set_footers(pages)
        return pages

    def _build_menu_pages(self, leaves: list[Leaf], title: str, detail: str) -> list[discord.Embed]:
        pages: list[discord.Embed] = []
        for chunk in self._chunk_by_module(leaves, max_fields=8):
            embed = discord.Embed(title=title, color=discord.Color.blurple())
            if detail and pages == []:
                embed.description = detail
            for module_name, ls in chunk:
                embed.add_field(
                    name=module_name.title(),
                    value="\n".join(self._command_line(leaf) for leaf in ls),
                    inline=False,
                )
            pages.append(embed)
        if not pages:
            pages = [
                discord.Embed(
                    title=title,
                    description="No commands in this section are enabled for this server.",
                )
            ]
        self._set_footers(pages)
        return pages

    async def _send_paginated(self, interaction: discord.Interaction, pages: list[discord.Embed],
                              picker_paths: list[str]) -> None:
        view = command_picker_view(dispatcher=self, paths=picker_paths) if picker_paths else None
        paginator = getattr(self.bot, "paginator", None)
        if paginator is None:
            if view is not None:
                await interaction.response.send_message(embed=pages[0], view=view)
            else:
                await interaction.response.send_message(embed=pages[0])
            return
        await paginator.send(interaction, pages, view=view)

    async def _show_module_menu(self, interaction: discord.Interaction, module_name: str, guild_id) -> None:
        leaves = [
            self._registry[p] for p in self._module_paths.get(module_name, [])
            if self._path_enabled(guild_id, self._registry[p])
        ]
        detail = (
            f"`/{self._group_name()} <command> [args...]` — pick a command below or "
            "type it after the slash command."
        )
        pages = self._build_menu_pages(leaves, title=f"🐺 {module_name.title()} commands", detail=detail)
        picker = [leaf.path for leaf in leaves]
        await self._send_paginated(interaction, pages, picker)

    async def _show_menu(self, interaction: discord.Interaction, title: str, paths: list[str],
                         guild_id, detail: str = "") -> None:
        leaves = [self._registry[p] for p in paths if self._path_enabled(guild_id, self._registry[p])]
        pages = self._build_menu_pages(leaves, title=title, detail=detail)
        picker = [leaf.path for leaf in leaves]
        await self._send_paginated(interaction, pages, picker)

    async def _show_overview(self, interaction: discord.Interaction, guild_id) -> None:
        pages = self._build_overview_pages(guild_id)
        enabled = [leaf.path for leaf in self._enabled_leaves(guild_id)]
        await self._send_paginated(interaction, pages, enabled)

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
            # Fail closed: on any state/DB error, don't advertise a module's
            # commands (a disabled-module error on invoke is worse than the
            # command being absent from autocomplete).
            logger.exception(
                "Failed to resolve enablement for module %s in guild %s — failing closed",
                leaf.module_name,
                guild_id,
            )
            return False


# ── Parameter / arg parsing helpers ──────────────────


async def parse_args_to_kwargs(
    interaction: discord.Interaction, command, args: str
) -> dict[str, Any]:
    """Parse the free-form ``args`` string into the leaf's typed parameters.

    Reuses the same token→type conversion the prefix adapter used, but resolves
    mentions/roles/channels against the interaction's guild instead of a text
    command context.

    The FINAL string parameter is a free-form sink: it consumes every remaining
    token (joined with spaces) so multi-word content (reasons, messages, notes)
    is preserved instead of being shredded into one word per parameter. When the
    tokens run out early, the remaining parameters are left unset so the
    callback's own defaults apply — we never fabricate a default target.
    """
    params = list(getattr(command, "parameters", []))
    tokens = (args or "").split()
    kwargs: dict[str, Any] = {}
    for i, param in enumerate(params):
        if not tokens:
            break
        t = param.type
        is_last = i == len(params) - 1
        if t is discord.AppCommandOptionType.string:
            if is_last:
                kwargs[param.name] = " ".join(tokens)
                tokens = []
            else:
                kwargs[param.name] = tokens.pop(0)
        elif t is discord.AppCommandOptionType.number:
            try:
                kwargs[param.name] = float(tokens.pop(0))
            except (TypeError, ValueError):
                kwargs[param.name] = 0.0
        elif t is discord.AppCommandOptionType.integer:
            try:
                kwargs[param.name] = int(tokens.pop(0))
            except (TypeError, ValueError):
                kwargs[param.name] = 0
        elif t is discord.AppCommandOptionType.boolean:
            raw = tokens.pop(0)
            kwargs[param.name] = raw.strip().lower() in (
                "true", "1", "yes", "on", "y", "enabled", "public",
            )
        elif t in (discord.AppCommandOptionType.user, discord.AppCommandOptionType.mentionable):
            kwargs[param.name] = await _resolve_member(interaction, tokens.pop(0))
        elif t is discord.AppCommandOptionType.role:
            kwargs[param.name] = await _resolve_role(interaction, tokens.pop(0))
        elif t is discord.AppCommandOptionType.channel:
            kwargs[param.name] = await _resolve_channel(interaction, tokens.pop(0))
    return kwargs


def _unresolved_required_target(command, kwargs: dict[str, Any]) -> str | None:
    """Name of a required member/role/channel param that failed to resolve.

    Returns ``None`` when every required target resolved. Lets the dispatcher
    show a clear "not found" error instead of acting on a default (e.g. warning
    the invoker when a mistyped mention failed to resolve).
    """
    for p in getattr(command, "parameters", []):
        if getattr(p, "required", False) and kwargs.get(p.name) is None:
            return p.name
    return None


async def _resolve_member(interaction, raw: str):
    guild = getattr(interaction, "guild", None)
    if guild is None:
        return None
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
    return None


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
