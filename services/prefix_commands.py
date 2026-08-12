"""Prefix-command adapter: expose module slash-command handlers as text commands.

Bark runs on discord.ext.commands.Bot with a configurable ``command_prefix``
(e.g. ``bark!`` -> ``bark!help``). Modules today expose their commands as
``discord.app_commands.Command`` (slash) via ``_make_<name>_command``
factories. This adapter registers a ``discord.ext.commands.Command`` for each
such handler and invokes the original slash handler through a message-bound
interaction shim, so no module business logic is rewritten.

The shim translates the small ``Interaction`` surface the handlers use
(``response``, ``followup``, ``guild``, ``user``, ``guild_id``) onto the real
``commands.Context``/``Message``.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from modules.base import BarkModule

logger = logging.getLogger("bark.services.prefix_commands")


class PrefixResponse:
    """Mimics ``InteractionResponse`` enough for the handlers: defer/send/edit."""

    def __init__(self, ctx: commands.Context) -> None:
        self._ctx = ctx
        self._done = False

    def is_done(self) -> bool:
        return self._done

    async def defer(self, *, ephemeral: bool = False, **kwargs: Any) -> None:
        # No-op: a text command is already "deferred" (we reply directly).
        self._done = True

    async def send_message(
        self,
        content: str | None = None,
        embed: discord.Embed | None = None,
        embeds: list[discord.Embed] | None = None,
        ephemeral: bool = False,
        **kwargs: Any,
    ) -> discord.Message:
        self._done = True
        if embed is not None:
            embeds = [embed]
        if embeds:
            return await self._ctx.send(content=content, embeds=embeds, **kwargs)
        return await self._ctx.send(content=content, **kwargs)

    async def edit_message(self, **kwargs: Any) -> None:
        self._done = True


class PrefixFollowup:
    """Mimics ``Interaction.followup`` — a thin send wrapper."""

    def __init__(self, ctx: commands.Context) -> None:
        self._ctx = ctx

    async def send(
        self,
        content: str | None = None,
        embed: discord.Embed | None = None,
        embeds: list[discord.Embed] | None = None,
        ephemeral: bool = False,
        **kwargs: Any,
    ) -> discord.Message:
        if embed is not None:
            embeds = [embed]
        if embeds:
            return await self._ctx.send(content=content, embeds=embeds, **kwargs)
        return await self._ctx.send(content=content, **kwargs)


class PrefixInteraction:
    """A read-only ``Interaction``-like object bound to a real message."""

    def __init__(self, ctx: commands.Context) -> None:
        self._ctx = ctx
        self.response = PrefixResponse(ctx)
        self.followup = PrefixFollowup(ctx)
        self.user = ctx.author
        self.guild = ctx.guild
        self.guild_id = ctx.guild.id if ctx.guild else None
        self.channel = ctx.channel
        self.type = discord.InteractionType.application_command
        self.id = ctx.message.id
        self.command = None
        self.command_failed = False
        self.data = {"name": ctx.command.name if ctx.command else "", "id": str(ctx.message.id), "type": 1}

    async def original_response(self) -> discord.Message:
        return self._ctx.message

    async def edit_original_response(self, **kwargs: Any) -> None:
        await self._ctx.message.edit(**kwargs)

    async def defer(self, *, ephemeral: bool = False, **kwargs: Any) -> None:
        self._done = True


def _make_dispatch(slash_leaf):
    """Return ``async (ctx, *raw_args)`` that dispatches one slash command leaf.

    The returned callback converts raw message tokens to typed kwargs from the
    leaf's parameter metadata, builds a message-bound interaction shim, and
    invokes the original handler. The handler is a closure over the module (it
    captures ``self`` at factory time), so it is called as ``callback(shim)``.
    """
    from discord.app_commands.commands import AppCommandOptionType

    params = list(getattr(slash_leaf, "parameters", []))
    callback = cast(Any, slash_leaf.callback)

    async def dispatch(ctx: commands.Context, *raw_args: str) -> None:
        interaction = PrefixInteraction(ctx)
        kwargs: dict[str, Any] = {}
        tokens = list(raw_args)
        for param in params:
            t = param.type
            if t in (AppCommandOptionType.string, AppCommandOptionType.number):
                kwargs[param.name] = tokens.pop(0) if tokens else (None if not param.required else "")
            elif t is AppCommandOptionType.integer:
                kwargs[param.name] = _to_int(tokens.pop(0)) if tokens else 0
            elif t is AppCommandOptionType.boolean:
                kwargs[param.name] = _to_bool(tokens.pop(0)) if tokens else False
            elif t in (AppCommandOptionType.user, AppCommandOptionType.mentionable):
                kwargs[param.name] = await _to_member_or_user(ctx, tokens.pop(0)) if tokens else ctx.author
            elif t is AppCommandOptionType.role:
                kwargs[param.name] = await _to_role(ctx, tokens.pop(0)) if tokens else None
            elif t is AppCommandOptionType.channel:
                kwargs[param.name] = await _to_channel(ctx, tokens.pop(0)) if tokens else None
        await callback(interaction, **kwargs)

    return dispatch


def build_prefix_command(
    module: BarkModule,
    cmd_name: str,
    slash_cmd,
):
    """Build a ``commands.Command``/``commands.Group`` for a module's slash command.

    A leaf ``app_commands.Command`` becomes a flat ``bark!<cmd>`` text command.
    An ``app_commands.Group`` (e.g. trivia) becomes a ``bark!<group> <sub>``
    command group, so subcommand paths survive in the text-command model.
    """
    children = getattr(slash_cmd, "commands", None)
    if children:  # it's a Group -> build a text-command group with subcommands
        async def _group_bare(ctx: commands.Context) -> None:  # pragma: no cover
            names = ", ".join(getattr(c, "name", "") for c in children)
            await ctx.send(f"Subcommands: {names}")

        group: commands.Group = commands.Group(
            _group_bare,
            name=cmd_name,
            description=getattr(slash_cmd, "description", "") or "",
        )
        for sub in children:
            sub_name = getattr(sub, "name", "")
            sub_cmd = build_prefix_command(module, sub_name, sub)
            group.add_command(sub_cmd)
        return group

    dispatch = _make_dispatch(slash_cmd)
    return commands.Command(
        dispatch,
        name=cmd_name,
        description=getattr(slash_cmd, "description", "") or "",
    )



def _to_int(raw: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _to_bool(raw: str) -> bool:
    return raw.strip().lower() in ("true", "1", "yes", "on", "y", "enabled")


async def _to_member_or_user(ctx: commands.Context, raw: str):
    for conv in (commands.MemberConverter(), commands.UserConverter()):
        try:
            return await conv.convert(ctx, raw)
        except Exception:
            continue
    return ctx.author


async def _to_role(ctx: commands.Context, raw: str):
    try:
        return await commands.RoleConverter().convert(ctx, raw)
    except Exception:
        return None


async def _to_channel(ctx: commands.Context, raw: str):
    for conv in (
        commands.TextChannelConverter(),
        commands.VoiceChannelConverter(),
    ):
        try:
            return await conv.convert(ctx, raw)
        except Exception:
            continue
    return None
