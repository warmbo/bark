"""Bark Auto Voice module.

Creates disposable voice channels when a member joins a configured primary
channel.  The module intentionally understands AVC's legacy naming tokens while
exposing the behavior through Bark's dashboard schema.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

import discord

from modules.base import (
    BarkModule,
    CommandRegistration,
    EventRegistration,
    PageRegistration,
    PermissionDefinition,
)


@dataclass(slots=True)
class ManagedChannel:
    guild_id: int
    owner_id: int
    sequence: int = 1


# Config groups — the dashboard schema is organised into these sections;
# each group maps to its flat keys so legacy (pre-grouping) configs keep
# working and are lifted into the grouped shape on read.
CONFIG_GROUPS: dict[str, list[str]] = {
    "channel": ["primary_channel_id", "channel_name_template", "fallback_name"],
    "naming": ["name_uppercase", "name_lowercase", "name_titlecase"],
    "limits": ["user_limit", "bitrate_kbps", "max_channels_per_user"],
    "access": [
        "inherit_permissions",
        "private_by_default",
        "required_role_id",
        "owner_can_rename",
        "owner_can_limit",
        "owner_can_lock",
    ],
    "cleanup": ["empty_delete_delay_seconds"],
}

_KEY_TO_GROUP: dict[str, str] = {
    key: group for group, keys in CONFIG_GROUPS.items() for key in keys
}


def normalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Lift legacy flat keys into the grouped shape the dashboard schema uses.

    New saves are already grouped (``{"channel": {"primary_channel_id": …}}``);
    older configs stored the keys flat at the top level. Returns a merged
    dict so both shapes read identically, preferring the grouped values.
    Lifted flat keys are removed from the top level so the result matches
    the declared schema exactly (the validator would otherwise flag the
    orphaned flat keys as "unknown setting").
    """
    if not isinstance(raw, dict):
        return {}
    grouped: dict[str, Any] = {}
    for group, keys in CONFIG_GROUPS.items():
        values = raw.get(group)
        if isinstance(values, dict):
            grouped[group] = dict(values)
            continue
        lifted = {key: raw[key] for key in keys if key in raw}
        if lifted:
            grouped[group] = lifted
    result = dict(raw)
    result.update(grouped)
    # Drop the lifted flat keys now that they live in their group.
    for group, keys in CONFIG_GROUPS.items():
        if group in grouped:
            for key in keys:
                result.pop(key, None)
    return result


class AutoVoiceModule(BarkModule):
    """Create, configure, and clean up temporary Discord voice channels."""

    name = "auto_voice"
    version = "0.4.0"
    description = "Temporary voice channels created on demand, with dashboard configuration"
    author = "ZENHAWX"

    # Five config groups read more cleanly dispersed into columns than as a
    # single tall stack of fieldsets.
    config_layout = "columns"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._managed_channels: dict[int, ManagedChannel] = {}
        self._delete_tasks: dict[int, asyncio.Task] = {}
        self._rename_locks: dict[int, asyncio.Lock] = {}
        self._joins_in_progress: set[int] = set()
        self._channel_sequence: dict[int, int] = {}

    @staticmethod
    def _cfg(config: dict[str, Any], key: str, default=None):
        """Read a config key from its group, falling back to a legacy flat key."""
        group = _KEY_TO_GROUP.get(key)
        if group:
            section = config.get(group)
            if isinstance(section, dict) and key in section:
                return section[key]
        return config.get(key, default)

    async def load_dashboard_config(self, guild_id: int) -> dict[str, Any]:
        raw = await self.ctx.get_module_config(self.name, guild_id)
        return normalize_config(raw)

    def normalize_config(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Lift legacy flat keys into the grouped schema shape."""
        return normalize_config(raw)

    @property
    def managed_channel_ids(self) -> frozenset[int]:
        return frozenset(self._managed_channels)

    def get_events(self) -> list[EventRegistration]:
        return [
            EventRegistration("discord_voice_state", handler="_on_voice_state_update"),
            EventRegistration("discord_presence_update", handler="_on_presence_update"),
        ]

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration("voice_name", "Rename your temporary voice channel"),
            CommandRegistration("voice_limit", "Set your temporary channel user limit"),
            CommandRegistration("voice_lock", "Lock your temporary voice channel"),
            CommandRegistration("voice_unlock", "Unlock your temporary voice channel"),
        ]

    def get_dashboard_pages(self) -> list[PageRegistration]:
        return [
            PageRegistration(
                route="/guild/{guild_id}/modules/auto_voice",
                label="Auto Voice",
                icon="audio-lines",
                category="community",
            )
        ]

    def get_permissions(self) -> list[PermissionDefinition]:
        return [PermissionDefinition(name="auto_voice.manage", label="Manage Auto Voice Channels")]

    def get_about(self) -> list[dict]:
        return [
            {
                "title": "AVC-compatible temporary channels",
                "description": (
                    "Members join a primary voice channel and Bark creates a personal "
                    "channel, moves them into it, and removes it when empty. Existing AVC "
                    "templates using ## and @@game_name@@ are supported."
                ),
            },
            {
                "title": "Dashboard managed",
                "description": (
                    "Choose the primary channel, name template, bitrate, user limit, "
                    "permission behavior, owner controls, and cleanup delay from Bark."
                ),
            },
        ]

    def get_settings_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "description": "Configure AVC-compatible temporary voice channels.",
            "properties": {
                "channel": {
                    "type": "object",
                    "title": "Channel Setup",
                    "description": "Which channel starts a temporary voice channel and how new channels are named.",
                    "properties": {
                        "primary_channel_id": {
                            "type": "string",
                            "format": "voice_channel_select",
                            "title": "Join-to-Create Channel",
                            "description": "Joining this voice channel creates a temporary channel.",
                            "placeholder": "Select a voice channel...",
                        },
                        "channel_name_template": {
                            "type": "string",
                            "title": "Channel Name Template",
                            "description": (
                                "Template used to name every new temporary channel. "
                                "Tokens, AVC transforms, and examples are listed in the "
                                "Name template reference below this field. Watch the "
                                "live preview as you type."
                            ),
                            "default": "## [@@game_name@@]",
                            "maxLength": 100,
                        },
                        "fallback_name": {
                            "type": "string",
                            "title": "No-game Fallback",
                            "description": "Replaces @@game_name@@ in channel names with the detected game, or {game} when no activity is detected.",
                            "default": "General",
                            "maxLength": 100,
                        },
                    },
                },
                "naming": {
                    "type": "object",
                    "title": "Channel Naming",
                    "description": "Optional casing applied to the finished channel name.",
                    "properties": {
                        "name_uppercase": {
                            "type": "boolean",
                            "title": "ALL UPPERCASE",
                            "description": "Force the finished channel name to ALL UPPERCASE (overrides lowercase).",
                            "default": False,
                        },
                        "name_lowercase": {
                            "type": "boolean",
                            "title": "all lowercase",
                            "description": "Force the finished channel name to all lowercase.",
                            "default": False,
                        },
                        "name_titlecase": {
                            "type": "boolean",
                            "title": "Title Case",
                            "description": "Force the finished channel name to Title Case.",
                            "default": False,
                        },
                    },
                },
                "limits": {
                    "type": "object",
                    "title": "Limits & Quality",
                    "description": "Capacity and audio quality for every new temporary channel.",
                    "properties": {
                        "user_limit": {
                            "type": "integer",
                            "title": "Default User Limit",
                            "description": "0 means unlimited.",
                            "minimum": 0,
                            "maximum": 99,
                            "default": 0,
                        },
                        "bitrate_kbps": {
                            "type": "integer",
                            "title": "Bitrate (kbps)",
                            "minimum": 8,
                            "maximum": 384,
                            "default": 64,
                        },
                        "max_channels_per_user": {
                            "type": "integer",
                            "title": "Max Channels per User",
                            "description": "How many temporary channels one member may open at once (0 = unlimited).",
                            "minimum": 0,
                            "maximum": 50,
                            "default": 0,
                        },
                    },
                },
                "access": {
                    "type": "object",
                    "title": "Permissions & Privacy",
                    "description": "Who may create a channel, who can join it, and what the owner may do with it.",
                    "properties": {
                        "inherit_permissions": {
                            "type": "boolean",
                            "title": "Copy Primary Channel Permissions",
                            "default": True,
                        },
                        "private_by_default": {
                            "type": "boolean",
                            "title": "Private by Default",
                            "description": "Only the creator and Bark may connect initially.",
                            "default": False,
                        },
                        "required_role_id": {
                            "type": "string",
                            "format": "role_select",
                            "title": "Required Role",
                            "description": "Optional role required to create a temporary channel.",
                            "placeholder": "No role required",
                        },
                        "auto_join_role_id": {
                            "type": "string",
                            "format": "role_select",
                            "title": "Auto-Join Role",
                            "description": (
                                "When set, members with this role are automatically "
                                "granted access to every new temporary channel (connect "
                                "and view). Useful for a 'voice' role that should always "
                                "be able to hop into any temp channel."
                            ),
                            "placeholder": "No auto-join role",
                        },
                        "owner_can_rename": {
                            "type": "boolean",
                            "title": "Owner Can Rename",
                            "default": True,
                        },
                        "owner_can_limit": {
                            "type": "boolean",
                            "title": "Owner Can Change User Limit",
                            "default": True,
                        },
                        "owner_can_lock": {
                            "type": "boolean",
                            "title": "Owner Can Lock or Unlock",
                            "default": True,
                        },
                    },
                },
                "cleanup": {
                    "type": "object",
                    "title": "Cleanup",
                    "description": "When empty temporary channels are deleted.",
                    "properties": {
                        "empty_delete_delay_seconds": {
                            "type": "integer",
                            "title": "Empty-channel Cleanup Delay",
                            "description": "Seconds to wait before deleting an empty temporary channel.",
                            "minimum": 0,
                            "maximum": 3600,
                            "default": 0,
                        },
                    },
                },
            },
        }

    async def enable(self) -> None:
        self._logger.info("Enabling auto voice module v%s", self.version)
        await self._recover_managed_channels()

    async def _recover_managed_channels(self) -> None:
        """Restore ownership and cleanup tracking after a Bark restart."""
        rows = await self.ctx.list_auto_voice_channels()

        recovered_per_guild: dict[int, int] = {}
        for row in rows:
            guild_id = int(row.guild_id)
            channel_id = int(row.channel_id)
            guild = self.ctx.get_guild(guild_id)
            channel = None
            if guild is not None:
                get_channel = getattr(guild, "get_channel", None)
                if callable(get_channel):
                    channel = get_channel(channel_id)
                if channel is None:
                    channel = next(
                        (
                            item
                            for item in getattr(guild, "channels", [])
                            if int(item.id) == channel_id
                        ),
                        None,
                    )

            if channel is None or not hasattr(channel, "members"):
                await self._forget_persisted_channel(channel_id)
                continue

            sequence_match = re.search(r"#(\d+)", str(channel.name))
            sequence = (
                int(sequence_match.group(1))
                if sequence_match
                else recovered_per_guild.get(guild_id, 0) + 1
            )
            self._managed_channels[channel_id] = ManagedChannel(
                guild_id=guild_id,
                owner_id=int(row.owner_id),
                sequence=sequence,
            )
            recovered_per_guild[guild_id] = max(recovered_per_guild.get(guild_id, 0), sequence)

            if not channel.members:
                config = await self.ctx.get_module_config(self.name, guild_id)
                await self._schedule_deletion(channel, config)

        for guild_id, count in recovered_per_guild.items():
            self._channel_sequence[guild_id] = max(self._channel_sequence.get(guild_id, 0), count)
        if rows:
            self._logger.info(
                "Recovered %d active temporary voice channel(s)",
                len(self._managed_channels),
            )

    async def disable(self) -> None:
        tasks = list(self._delete_tasks.values())
        self._delete_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._rename_locks.clear()
        self._joins_in_progress.clear()
        self._logger.info("Disabled auto voice module")

    def _make_voice_name_command(self):
        @discord.app_commands.command(
            name="voice_name", description="Rename your temporary voice channel"
        )
        async def voice_name(interaction: discord.Interaction, name: str):
            channel = await self._owned_channel(interaction)
            if channel is None:
                return
            guild_id = int(interaction.guild_id) if interaction.guild_id else 0
            config = await self.load_dashboard_config(guild_id)
            if not self._cfg(config, "owner_can_rename", True):
                await interaction.response.send_message(
                    "Renaming is disabled for channel owners.", ephemeral=True
                )
                return
            clean_name = " ".join(name.split())[:100]
            if not clean_name:
                await interaction.response.send_message(
                    "Channel name cannot be empty.", ephemeral=True
                )
                return
            try:
                await channel.edit(name=clean_name, reason="Bark Auto Voice: owner rename")
            except (discord.Forbidden, discord.HTTPException):
                await interaction.response.send_message(
                    "Bark could not rename that channel.", ephemeral=True
                )
                return
            await interaction.response.send_message(
                f"Channel renamed to **{clean_name}**.", ephemeral=True
            )

        return voice_name

    def _make_voice_limit_command(self):
        @discord.app_commands.command(
            name="voice_limit", description="Set your temporary voice channel user limit"
        )
        async def voice_limit(interaction: discord.Interaction, limit: int):
            channel = await self._owned_channel(interaction)
            if channel is None:
                return
            guild_id = int(interaction.guild_id) if interaction.guild_id else 0
            config = await self.load_dashboard_config(guild_id)
            if not self._cfg(config, "owner_can_limit", True):
                await interaction.response.send_message(
                    "Changing the user limit is disabled for channel owners.",
                    ephemeral=True,
                )
                return
            limit = max(0, min(99, int(limit)))
            try:
                await channel.edit(
                    user_limit=limit,
                    reason="Bark Auto Voice: owner changed user limit",
                )
            except (discord.Forbidden, discord.HTTPException):
                await interaction.response.send_message(
                    "Bark could not change that channel's user limit.", ephemeral=True
                )
                return
            label = "unlimited" if limit == 0 else str(limit)
            await interaction.response.send_message(
                f"Channel user limit set to **{label}**.", ephemeral=True
            )

        return voice_limit

    def _make_voice_lock_command(self):
        return self._make_voice_access_command(locked=True)

    def _make_voice_unlock_command(self):
        return self._make_voice_access_command(locked=False)

    def _make_voice_access_command(self, *, locked: bool):
        command_name = "voice_lock" if locked else "voice_unlock"
        description = (
            "Lock your temporary voice channel" if locked else "Unlock your temporary voice channel"
        )

        @discord.app_commands.command(name=command_name, description=description)
        async def voice_access(interaction: discord.Interaction):
            channel = await self._owned_channel(interaction)
            if channel is None:
                return
            guild_id = int(interaction.guild_id) if interaction.guild_id else 0
            config = await self.load_dashboard_config(guild_id)
            if not self._cfg(config, "owner_can_lock", True):
                await interaction.response.send_message(
                    "Locking is disabled for channel owners.", ephemeral=True
                )
                return
            action = "locked" if locked else "unlocked"
            if interaction.guild is None:
                return
            try:
                await channel.set_permissions(
                    interaction.guild.default_role,
                    connect=False if locked else None,
                    reason=f"Bark Auto Voice: owner {action} channel",
                )
            except (discord.Forbidden, discord.HTTPException):
                await interaction.response.send_message(
                    f"Bark could not {command_name.removeprefix('voice_')} that channel.",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(f"Channel {action}.", ephemeral=True)

        return voice_access

    async def _owned_channel(self, interaction):
        user = getattr(interaction, "user", None)
        voice = getattr(user, "voice", None)
        channel = getattr(voice, "channel", None)
        state = self._managed_channels.get(int(channel.id)) if channel else None
        if channel is None or user is None:
            await interaction.response.send_message(
                "You must own and be connected to a Bark temporary voice channel.",
                ephemeral=True,
            )
            return None
        if state is None or int(state.owner_id) != int(user.id):
            await interaction.response.send_message(
                "You must own and be connected to a Bark temporary voice channel.",
                ephemeral=True,
            )
            return None
        return channel

    async def _on_voice_state_update(self, event_type: str, **data) -> None:
        member = data.get("member")
        before = data.get("before")
        after = data.get("after")
        if member is None or getattr(member, "bot", False):
            return

        before_channel = getattr(before, "channel", None)
        after_channel = getattr(after, "channel", None)

        if after_channel is not None:
            self._cancel_deletion(int(after_channel.id))

        config = await self.load_dashboard_config(int(member.guild.id))
        primary_id = self._as_int(self._cfg(config, "primary_channel_id"))
        if after_channel is not None and primary_id == int(after_channel.id):
            await self._create_for_member(member, after_channel, config)

        if (
            before_channel is not None
            and int(before_channel.id) in self._managed_channels
            and not getattr(before_channel, "members", [])
        ):
            await self._schedule_deletion(before_channel, config)

        refreshed: set[int] = set()
        for channel in (before_channel, after_channel):
            channel_id = int(channel.id) if channel is not None else 0
            if (
                channel_id in self._managed_channels
                and channel_id not in refreshed
                and getattr(channel, "members", [])
            ):
                refreshed.add(channel_id)
                await self._refresh_channel_name(channel, config)

    async def _on_presence_update(self, event_type: str, **data) -> None:
        member = data.get("after")
        if member is None:
            return
        voice = getattr(member, "voice", None)
        channel = getattr(voice, "channel", None)
        if channel is None or int(channel.id) not in self._managed_channels:
            return
        guild = getattr(member, "guild", None)
        if guild is None:
            return
        config = await self.load_dashboard_config(int(guild.id))
        await self._refresh_channel_name(channel, config)

    async def _create_for_member(self, member, primary, config: dict[str, Any]) -> None:
        member_id = int(member.id)
        if member_id in self._joins_in_progress:
            return
        if not self._has_required_role(member, self._cfg(config, "required_role_id")):
            return
        max_channels = self._config_int(
            config, "max_channels_per_user", default=0, minimum=0, maximum=50
        )
        if max_channels > 0:
            owned = sum(
                1
                for ch in self._managed_channels.values()
                if ch.owner_id == member_id and ch.guild_id == int(member.guild.id)
            )
            if owned >= max_channels:
                return

        self._joins_in_progress.add(member_id)
        created = None
        try:
            sequence = self._next_sequence(int(member.guild.id))
            name = self._render_name(member, config, index=sequence)
            overwrites = self._build_overwrites(member, primary, config)
            requested_bitrate = (
                self._config_int(config, "bitrate_kbps", default=64, minimum=8, maximum=384) * 1000
            )
            guild_bitrate_limit = int(getattr(member.guild, "bitrate_limit", requested_bitrate))
            created = await member.guild.create_voice_channel(
                name=name,
                category=getattr(primary, "category", None),
                overwrites=overwrites,
                bitrate=min(requested_bitrate, guild_bitrate_limit),
                user_limit=self._config_int(config, "user_limit", default=0, minimum=0, maximum=99),
                reason="Bark Auto Voice: join-to-create",
            )
            self._managed_channels[int(created.id)] = ManagedChannel(
                guild_id=int(member.guild.id), owner_id=member_id, sequence=sequence
            )
            await member.move_to(created, reason="Bark Auto Voice: temporary channel created")
            await self._persist_managed_channel(created, member, primary)
            # Auto-Join Role: grant the configured role connect + view on the
            # new channel so its holders can always hop in.
            auto_join_role_id = self._cfg(config, "auto_join_role_id")
            if auto_join_role_id:
                role = member.guild.get_role(int(auto_join_role_id))
                if role is not None:
                    try:
                        await created.set_permissions(
                            role,
                            view_channel=True,
                            connect=True,
                            reason="Bark Auto Voice: auto-join role access",
                        )
                    except (discord.Forbidden, discord.HTTPException):
                        self._logger.warning(
                            "Could not grant auto-join role %s on temp channel", role.id
                        )
        except (discord.Forbidden, discord.HTTPException, TypeError, ValueError):
            self._logger.exception("Failed to create temporary voice channel")
            if created is not None:
                self._managed_channels.pop(int(created.id), None)
                try:
                    await created.delete(reason="Bark Auto Voice: creation rollback")
                except (discord.Forbidden, discord.HTTPException):
                    pass
        finally:
            self._joins_in_progress.discard(member_id)

    async def _persist_managed_channel(self, channel, member, primary) -> None:
        await self.ctx.save_auto_voice_channel(
            channel_id=int(channel.id),
            guild_id=int(member.guild.id),
            owner_id=int(member.id),
            primary_channel_id=int(primary.id),
        )

    async def _schedule_deletion(self, channel, config: dict[str, Any]) -> None:
        channel_id = int(channel.id)
        if channel_id in self._delete_tasks:
            return
        delay = self._config_int(
            config,
            "empty_delete_delay_seconds",
            default=5,
            minimum=0,
            maximum=3600,
        )

        async def delayed_delete() -> None:
            try:
                # Even zero-delay cleanup yields once and remains cancellable if
                # Discord reports a rejoin on the next event-loop turn.
                await asyncio.sleep(delay)
                await self._delete_if_empty(channel)
            except Exception:
                self._logger.exception("Failed to delete auto-voice channel %s", channel_id)
            finally:
                self._delete_tasks.pop(channel_id, None)

        self._delete_tasks[channel_id] = asyncio.create_task(delayed_delete())

    async def _delete_if_empty(self, channel) -> None:
        channel_id = int(channel.id)
        if channel_id not in self._managed_channels:
            return
        if getattr(channel, "members", []):
            return
        try:
            await channel.delete(reason="Bark Auto Voice: channel empty")
        except (discord.NotFound, discord.Forbidden):
            pass
        except discord.HTTPException:
            self._logger.exception("Failed to delete empty temporary voice channel %s", channel_id)
            return
        self._managed_channels.pop(channel_id, None)
        self._rename_locks.pop(channel_id, None)
        await self._forget_persisted_channel(channel_id)

    async def _forget_persisted_channel(self, channel_id: int) -> None:
        await self.ctx.delete_auto_voice_channel(channel_id)

    def _cancel_deletion(self, channel_id: int) -> None:
        task = self._delete_tasks.pop(channel_id, None)
        if task is not None:
            task.cancel()

    @staticmethod
    def _config_int(
        config: dict[str, Any],
        key: str,
        *,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        value = AutoVoiceModule._cfg(config, key, default)
        try:
            parsed = int(value) if value not in (None, "") else default
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    def _next_sequence(self, guild_id: int) -> int:
        index = self._channel_sequence.get(guild_id, 0) + 1
        self._channel_sequence[guild_id] = index
        return index

    def _render_name(
        self,
        member,
        config: dict[str, Any],
        *,
        game: str | None = None,
        index: int | None = None,
    ) -> str:
        template = str(self._cfg(config, "channel_name_template") or "## [@@game_name@@]")
        fallback = str(self._cfg(config, "fallback_name") or "General")
        game = game or self._member_game(member) or fallback
        guild_id = int(member.guild.id)
        index = index or self._next_sequence(guild_id)
        replacements = {
            "##": f"#{index}",
            "@@game_name@@": game,
            "{game}": game,
            "{display_name}": str(getattr(member, "display_name", member.name)),
            "{username}": str(member.name),
            "{guild}": str(member.guild.name),
        }
        for token, value in replacements.items():
            template = template.replace(token, value)
        template = self._apply_avc_transforms(template)
        name = " ".join(template.split())[:100]
        if self._cfg(config, "name_uppercase"):
            name = name.upper()
        elif self._cfg(config, "name_lowercase"):
            name = name.lower()
        elif self._cfg(config, "name_titlecase"):
            name = name.title()
        return name or f"Voice {index:02d}"

    async def _refresh_channel_name(self, channel, config: dict[str, Any]) -> None:
        channel_id = int(channel.id)
        lock = self._rename_locks.setdefault(channel_id, asyncio.Lock())
        async with lock:
            await self._refresh_channel_name_locked(channel, config)

    async def _refresh_channel_name_locked(self, channel, config: dict[str, Any]) -> None:
        state = self._managed_channels.get(int(channel.id))
        members = [
            member
            for member in (getattr(channel, "members", []) or [])
            if not getattr(member, "bot", False)
        ]
        if state is None or not members:
            return
        owner = None
        get_member = getattr(channel.guild, "get_member", None)
        if callable(get_member):
            owner = get_member(int(state.owner_id))
        owner = owner or members[0]
        game = self._majority_game(members) or str(self._cfg(config, "fallback_name") or "General")
        desired_name = self._render_name(
            owner,
            config,
            game=game,
            index=int(getattr(state, "sequence", 1)),
        )
        if desired_name == str(channel.name):
            return
        try:
            await channel.edit(
                name=desired_name,
                reason="Bark Auto Voice: majority game changed",
            )
            channel.name = desired_name
        except (discord.Forbidden, discord.HTTPException):
            self._logger.exception("Failed to update temporary voice channel %s name", channel.id)

    @classmethod
    def _majority_game(cls, members) -> str | None:
        games = [game for member in members if (game := cls._member_game(member))]
        if not games:
            return None
        counts = Counter(games)
        game, count = counts.most_common(1)[0]
        return game if count > len(members) / 2 else None

    @staticmethod
    def _apply_avc_transforms(template: str) -> str:
        """Apply AVC's quoted text transforms used by legacy templates."""
        transform = re.compile(r'""([^":]+):\s*(.*?)""')
        operations = {
            "caps": str.upper,
            "upper": str.upper,
            "lower": str.lower,
            "title": str.title,
            "swap": str.swapcase,
            "acro": lambda value: "".join(word[0].upper() for word in value.split() if word),
            "spaces": lambda value: "".join(value.split()),
        }

        def replace(match: re.Match[str]) -> str:
            value = match.group(2).strip()
            for mode in match.group(1).split("+"):
                operation = operations.get(mode.strip().lower())
                if operation is not None:
                    value = operation(value)
            return value

        while transform.search(template):
            template = transform.sub(replace, template)
        return template

    @staticmethod
    def _member_game(member) -> str | None:
        for activity in getattr(member, "activities", []) or []:
            activity_type = getattr(activity, "type", None)
            if activity_type not in (None, discord.ActivityType.playing):
                continue
            name = getattr(activity, "name", None)
            if name:
                return str(name)
        return None

    def _build_overwrites(self, member, primary, config: dict[str, Any]):
        if self._cfg(config, "inherit_permissions", True):
            overwrites = dict(getattr(primary, "overwrites", {}) or {})
        else:
            overwrites = {}
        if self._cfg(config, "private_by_default", False):
            overwrites[member.guild.default_role] = discord.PermissionOverwrite(connect=False)
            overwrites[member] = discord.PermissionOverwrite(view_channel=True, connect=True)
            bot_member = getattr(member.guild, "me", None)
            if bot_member is not None:
                overwrites[bot_member] = discord.PermissionOverwrite(
                    view_channel=True, connect=True, manage_channels=True, move_members=True
                )
        return overwrites

    @staticmethod
    def _has_required_role(member, configured_role_id) -> bool:
        role_id = AutoVoiceModule._as_int(configured_role_id)
        if role_id is None:
            return True
        return any(int(role.id) == role_id for role in getattr(member, "roles", []))

    @staticmethod
    def _as_int(value) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None
