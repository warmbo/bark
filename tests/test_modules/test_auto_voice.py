import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from modules.auto_voice.module import AutoVoiceModule


class _HashableNamespace(SimpleNamespace):
    __hash__ = object.__hash__


class _Context:
    def __init__(self, config):
        self.get_module_config = AsyncMock(return_value=config)
        self.save_module_config = AsyncMock()
        self.save_auto_voice_channel = AsyncMock()
        self.list_auto_voice_channels = AsyncMock(return_value=[])
        self.delete_auto_voice_channel = AsyncMock()
        self.get_guild = MagicMock(return_value=None)
        self.bot = SimpleNamespace(user=SimpleNamespace(id=999))


def _use_database_state(ctx):
    """Bind BarkContext's real persistence methods to a lightweight test context."""
    from services.bark_context import BarkContext

    for name in (
        "save_auto_voice_channel",
        "list_auto_voice_channels",
        "delete_auto_voice_channel",
    ):
        setattr(ctx, name, getattr(BarkContext, name).__get__(ctx, type(ctx)))


def _voice_fixture(config=None):
    config = config or {
        "primary_channel_id": "100",
        "channel_name_template": "## {display_name}'s room",
        "user_limit": 6,
        "bitrate_kbps": 64,
        "inherit_permissions": True,
        "private_by_default": False,
        "empty_delete_delay_seconds": 0,
    }
    ctx = _Context(config)
    category = SimpleNamespace(id=50)
    primary = SimpleNamespace(
        id=100,
        name="Join to Create",
        category=category,
        overwrites={"existing": "overwrite"},
        position=4,
    )
    temporary = SimpleNamespace(
        id=200,
        name="01 Cody's room",
        members=[],
        category=category,
        delete=AsyncMock(),
        edit=AsyncMock(),
    )
    guild = SimpleNamespace(
        id=10,
        name="ZENHAWX",
        channels=[primary],
        default_role=_HashableNamespace(id=10),
        me=_HashableNamespace(id=999),
        bitrate_limit=96_000,
        create_voice_channel=AsyncMock(return_value=temporary),
    )
    primary.guild = guild
    temporary.guild = guild
    member = _HashableNamespace(
        id=42,
        bot=False,
        name="cody",
        display_name="Cody",
        guild=guild,
        roles=[],
        activities=[],
        voice=None,
        move_to=AsyncMock(),
    )
    disconnected = SimpleNamespace(channel=None)
    joined_primary = SimpleNamespace(channel=primary)
    return ctx, guild, member, primary, temporary, disconnected, joined_primary


def _schema_field(schema, key):
    """Find a schema property by flat key across the grouped sections."""
    for section in schema["properties"].values():
        if isinstance(section, dict) and key in section.get("properties", {}):
            return section["properties"][key]
    return None


def test_schema_groups_cover_all_flat_keys_in_sections():
    module = AutoVoiceModule(_Context({}))
    schema = module.get_settings_schema()

    # Every previously-flat key survives, now inside a named section.
    all_keys = [
        "primary_channel_id", "channel_name_template", "fallback_name",
        "name_uppercase", "name_lowercase", "name_titlecase",
        "user_limit", "bitrate_kbps", "max_channels_per_user",
        "inherit_permissions", "private_by_default", "required_role_id",
        "auto_join_role_id",
        "owner_can_rename", "owner_can_limit", "owner_can_lock",
        "empty_delete_delay_seconds",
    ]
    for key in all_keys:
        assert _schema_field(schema, key) is not None, f"{key} missing from schema"

    # The casing toggles were consolidated into "Channel Setup & Naming" so the
    # 2-column layout flows 4 balanced sections instead of 5 ragged ones.
    sections = schema["properties"]
    assert set(sections) == {"channel", "limits", "access", "cleanup"}
    # No flat top-level fields remain.
    for section in sections.values():
        assert section["type"] == "object" and section["properties"]


def test_schema_exposes_avc_behavior_as_dashboard_configuration():
    module = AutoVoiceModule(_Context({}))
    schema = module.get_settings_schema()

    assert _schema_field(schema, "primary_channel_id")["format"] == "voice_channel_select"
    assert _schema_field(schema, "channel_name_template")["default"] == "## [@@game_name@@]"
    assert _schema_field(schema, "user_limit")["maximum"] == 99
    assert _schema_field(schema, "bitrate_kbps")["minimum"] == 8
    assert _schema_field(schema, "inherit_permissions")["type"] == "boolean"
    assert _schema_field(schema, "private_by_default")["type"] == "boolean"
    assert _schema_field(schema, "empty_delete_delay_seconds")["minimum"] == 0
    assert _schema_field(schema, "owner_can_rename")["type"] == "boolean"
    assert _schema_field(schema, "owner_can_limit")["type"] == "boolean"
    assert _schema_field(schema, "owner_can_lock")["type"] == "boolean"


def test_normalize_config_lifts_legacy_flat_keys():
    from modules.auto_voice.module import normalize_config

    legacy = {
        "primary_channel_id": "111",
        "channel_name_template": "## Game",
        "user_limit": 5,
        "owner_can_rename": False,
        "custom_key": "kept-as-is",
    }
    normalized = normalize_config(legacy)
    assert normalized["channel"]["primary_channel_id"] == "111"
    assert normalized["channel"]["channel_name_template"] == "## Game"
    assert normalized["limits"]["user_limit"] == 5
    assert normalized["access"]["owner_can_rename"] is False
    assert normalized["custom_key"] == "kept-as-is"
    # Grouped configs pass through untouched.
    grouped = {"limits": {"user_limit": 7}}
    assert normalize_config(grouped)["limits"]["user_limit"] == 7


@pytest.mark.asyncio
async def test_cfg_reads_grouped_and_legacy_flat_keys():
    module = AutoVoiceModule(_Context({}))
    grouped = {"naming": {"name_uppercase": True}, "limits": {"user_limit": 12}}
    assert module._cfg(grouped, "name_uppercase") is True
    assert module._cfg(grouped, "user_limit") == 12
    assert module._cfg(grouped, "owner_can_rename", True) is True  # default
    legacy = {"name_uppercase": True, "user_limit": 12}
    assert module._cfg(legacy, "name_uppercase") is True
    assert module._cfg(legacy, "user_limit") == 12


@pytest.mark.asyncio
async def test_joining_primary_creates_configured_channel_and_moves_member():
    ctx, guild, member, primary, temporary, disconnected, joined_primary = _voice_fixture()
    module = AutoVoiceModule(ctx)

    await module._on_voice_state_update(
        "discord_voice_state", member=member, before=disconnected, after=joined_primary
    )

    guild.create_voice_channel.assert_awaited_once()
    kwargs = guild.create_voice_channel.await_args.kwargs
    assert kwargs["name"] == "#1 Cody's room"
    assert kwargs["category"] is primary.category
    assert kwargs["user_limit"] == 6
    assert kwargs["bitrate"] == 64_000
    assert kwargs["overwrites"] == primary.overwrites
    member.move_to.assert_awaited_once_with(
        temporary, reason="Bark Auto Voice: temporary channel created"
    )
    assert temporary.id in module.managed_channel_ids


@pytest.mark.asyncio
async def test_created_channel_is_persisted_for_restart_recovery(db):
    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.auto_voice import AutoVoiceChannel
    from database.models.guild import Guild

    ctx, guild, member, primary, temporary, disconnected, joined_primary = _voice_fixture()
    async with session_scope() as session:
        session.add(Guild(discord_id=str(guild.id), name=guild.name))
    _use_database_state(ctx)
    module = AutoVoiceModule(ctx)

    await module._on_voice_state_update(
        "discord_voice_state", member=member, before=disconnected, after=joined_primary
    )

    async with session_scope() as session:
        row = (await session.execute(select(AutoVoiceChannel))).scalar_one()
    assert row.channel_id == str(temporary.id)
    assert row.guild_id == str(guild.id)
    assert row.owner_id == str(member.id)
    assert row.primary_channel_id == str(primary.id)


@pytest.mark.asyncio
async def test_enable_recovers_occupied_temporary_channels_after_restart(db):
    from database.engine import session_scope
    from database.models.auto_voice import AutoVoiceChannel
    from database.models.guild import Guild

    ctx, guild, member, primary, temporary, *_ = _voice_fixture()
    async with session_scope() as session:
        session.add(Guild(discord_id=str(guild.id), name=guild.name))
    async with session_scope() as session:
        session.add(
            AutoVoiceChannel(
                channel_id=str(temporary.id),
                guild_id=str(guild.id),
                owner_id=str(member.id),
                primary_channel_id=str(primary.id),
            )
        )
    temporary.name = "#7 [General]"
    temporary.members = [member]
    guild.channels.append(temporary)
    _use_database_state(ctx)
    ctx.get_guild = MagicMock(return_value=guild)
    module = AutoVoiceModule(ctx)

    await module.enable()

    assert module.managed_channel_ids == frozenset({temporary.id})
    assert module._managed_channels[temporary.id].owner_id == member.id
    assert module._managed_channels[temporary.id].sequence == 7
    assert module._channel_sequence[guild.id] == 7
    temporary.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_blank_optional_numeric_settings_use_safe_defaults():
    ctx, guild, member, primary, _temporary, disconnected, joined_primary = _voice_fixture(
        {"primary_channel_id": "100", "user_limit": "", "bitrate_kbps": ""}
    )
    module = AutoVoiceModule(ctx)

    await module._on_voice_state_update(
        "discord_voice_state", member=member, before=disconnected, after=joined_primary
    )

    kwargs = guild.create_voice_channel.await_args.kwargs
    assert kwargs["user_limit"] == 0
    assert kwargs["bitrate"] == 64_000


@pytest.mark.asyncio
async def test_requested_bitrate_is_capped_to_the_guild_limit():
    config = {
        "primary_channel_id": "100",
        "channel_name_template": "## Room",
        "bitrate_kbps": 384,
        "empty_delete_delay_seconds": 0,
    }
    ctx, guild, member, primary, temporary, disconnected, joined_primary = _voice_fixture(config)
    module = AutoVoiceModule(ctx)

    await module._on_voice_state_update(
        "discord_voice_state", member=member, before=disconnected, after=joined_primary
    )

    assert guild.create_voice_channel.await_args.kwargs["bitrate"] == 96_000


@pytest.mark.asyncio
async def test_private_channels_do_not_bypass_owner_control_switches():
    config = {
        "primary_channel_id": "100",
        "private_by_default": True,
        "inherit_permissions": False,
        "empty_delete_delay_seconds": 0,
    }
    ctx, guild, member, primary, temporary, disconnected, joined_primary = _voice_fixture(config)
    module = AutoVoiceModule(ctx)

    await module._on_voice_state_update(
        "discord_voice_state", member=member, before=disconnected, after=joined_primary
    )

    overwrites = guild.create_voice_channel.await_args.kwargs["overwrites"]
    assert overwrites[guild.default_role].connect is False
    assert overwrites[member].connect is True
    assert overwrites[member].manage_channels is None
    assert overwrites[guild.me].manage_channels is True


@pytest.mark.asyncio
async def test_empty_managed_channel_is_deleted_when_last_member_leaves():
    ctx, guild, member, primary, temporary, disconnected, joined_primary = _voice_fixture()
    module = AutoVoiceModule(ctx)
    module._managed_channels[temporary.id] = SimpleNamespace(guild_id=guild.id, owner_id=member.id)
    left_temporary = SimpleNamespace(channel=temporary)

    await module._on_voice_state_update(
        "discord_voice_state", member=member, before=left_temporary, after=disconnected
    )
    temporary.delete.assert_not_awaited()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    temporary.delete.assert_awaited_once_with(reason="Bark Auto Voice: channel empty")
    assert temporary.id not in module.managed_channel_ids


@pytest.mark.asyncio
async def test_deleted_channel_is_removed_from_restart_recovery_state(db):
    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.auto_voice import AutoVoiceChannel
    from database.models.guild import Guild

    ctx, guild, member, primary, temporary, disconnected, joined_primary = _voice_fixture()
    async with session_scope() as session:
        session.add(Guild(discord_id=str(guild.id), name=guild.name))
    async with session_scope() as session:
        session.add(
            AutoVoiceChannel(
                channel_id=str(temporary.id),
                guild_id=str(guild.id),
                owner_id=str(member.id),
                primary_channel_id=str(primary.id),
            )
        )
    _use_database_state(ctx)
    module = AutoVoiceModule(ctx)
    module._managed_channels[temporary.id] = SimpleNamespace(guild_id=guild.id, owner_id=member.id)

    await module._on_voice_state_update(
        "discord_voice_state",
        member=member,
        before=SimpleNamespace(channel=temporary),
        after=disconnected,
    )
    cleanup_task = module._delete_tasks[temporary.id]
    await cleanup_task

    async with session_scope() as session:
        rows = (await session.execute(select(AutoVoiceChannel))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_pending_deletion_is_cancelled_when_member_rejoins():
    config = {
        "primary_channel_id": "100",
        "empty_delete_delay_seconds": 30,
    }
    ctx, guild, member, primary, temporary, disconnected, joined_primary = _voice_fixture(config)
    module = AutoVoiceModule(ctx)
    module._managed_channels[temporary.id] = SimpleNamespace(guild_id=guild.id, owner_id=member.id)
    temporary.members = []

    await module._on_voice_state_update(
        "discord_voice_state",
        member=member,
        before=SimpleNamespace(channel=temporary),
        after=disconnected,
    )
    assert temporary.id in module._delete_tasks

    temporary.members = [member]
    await module._on_voice_state_update(
        "discord_voice_state",
        member=member,
        before=disconnected,
        after=SimpleNamespace(channel=temporary),
    )
    await asyncio.sleep(0)

    temporary.delete.assert_not_awaited()
    assert temporary.id not in module._delete_tasks


def test_avc_numbering_and_lowercase_transform_are_compatible():
    ctx, _guild, member, *_ = _voice_fixture()
    member.activities = [SimpleNamespace(name="World Of Warcraft")]
    module = AutoVoiceModule(ctx)

    assert (
        module._render_name(
            member,
            {"channel_name_template": '## [""lower:@@game_name@@""]'},
        )
        == "#1 [world of warcraft]"
    )


def test_channel_sequence_is_unique_before_discord_creation_finishes():
    ctx, guild, member, *_ = _voice_fixture({"channel_name_template": "## Room"})
    module = AutoVoiceModule(ctx)
    other_member = _HashableNamespace(
        id=43,
        name="other",
        display_name="Other",
        guild=guild,
        activities=[],
    )

    assert module._render_name(member, {"channel_name_template": "## Room"}) == "#1 Room"
    assert module._render_name(other_member, {"channel_name_template": "## Room"}) == "#2 Room"


def test_name_case_flags_transform_finished_name():
    ctx, _guild, member, *_ = _voice_fixture({"channel_name_template": "## [@@game_name@@]"})
    member.activities = [SimpleNamespace(name="Counter-Strike 2")]
    module = AutoVoiceModule(ctx)
    base = {"channel_name_template": "## [@@game_name@@]", "index_hint": None}

    assert module._render_name(member, base, index=1) == "#1 [Counter-Strike 2]"
    assert (
        module._render_name(member, {**base, "name_uppercase": True}, index=1)
        == "#1 [COUNTER-STRIKE 2]"
    )
    assert (
        module._render_name(member, {**base, "name_lowercase": True}, index=1)
        == "#1 [counter-strike 2]"
    )
    assert (
        module._render_name(member, {**base, "name_titlecase": True}, index=1)
        == "#1 [Counter-Strike 2]"
    )


def test_name_uppercase_wins_over_lowercase():
    ctx, _guild, member, *_ = _voice_fixture({"channel_name_template": "## room"})
    module = AutoVoiceModule(ctx)
    assert (
        module._render_name(
            member,
            {"channel_name_template": "## room", "name_uppercase": True, "name_lowercase": True},
            index=1,
        )
        == "#1 ROOM"
    )


def test_game_detection_ignores_custom_status_before_playing_activity():
    ctx, _guild, member, *_ = _voice_fixture()
    member.activities = [
        SimpleNamespace(type=discord.ActivityType.custom, name="Custom Status"),
        SimpleNamespace(type=discord.ActivityType.playing, name="Minecraft"),
    ]

    assert AutoVoiceModule(ctx)._member_game(member) == "Minecraft"


@pytest.mark.asyncio
async def test_managed_channel_uses_game_played_by_majority_of_members():
    config = {
        "primary_channel_id": "100",
        "channel_name_template": "## [@@game_name@@]",
        "fallback_name": "Hangout",
    }
    ctx, guild, owner, _primary, temporary, disconnected, _joined = _voice_fixture(config)
    owner.activities = [SimpleNamespace(name="Minecraft")]
    player_two = _HashableNamespace(
        id=43,
        bot=False,
        name="two",
        display_name="Two",
        guild=guild,
        activities=[SimpleNamespace(name="Helldivers 2")],
    )
    player_three = _HashableNamespace(
        id=44,
        bot=False,
        name="three",
        display_name="Three",
        guild=guild,
        activities=[SimpleNamespace(name="Helldivers 2")],
    )
    temporary.members = [owner, player_two, player_three]
    guild.get_member = lambda member_id: owner if member_id == owner.id else None
    module = AutoVoiceModule(ctx)
    module._managed_channels[temporary.id] = SimpleNamespace(
        guild_id=guild.id, owner_id=owner.id, sequence=1
    )

    await module._on_voice_state_update(
        "discord_voice_state",
        member=player_three,
        before=disconnected,
        after=SimpleNamespace(channel=temporary),
    )

    temporary.edit.assert_awaited_once_with(
        name="#1 [Helldivers 2]",
        reason="Bark Auto Voice: majority game changed",
    )


@pytest.mark.asyncio
async def test_one_player_does_not_define_game_for_three_member_channel():
    config = {
        "channel_name_template": "## [@@game_name@@]",
        "fallback_name": "Hangout",
    }
    ctx, guild, owner, _primary, temporary, disconnected, _joined = _voice_fixture(config)
    owner.activities = [SimpleNamespace(name="Minecraft")]
    idle_two = _HashableNamespace(id=43, bot=False, guild=guild, activities=[])
    idle_three = _HashableNamespace(id=44, bot=False, guild=guild, activities=[])
    temporary.members = [owner, idle_two, idle_three]
    guild.get_member = lambda member_id: owner if member_id == owner.id else None
    module = AutoVoiceModule(ctx)
    module._managed_channels[temporary.id] = SimpleNamespace(
        guild_id=guild.id, owner_id=owner.id, sequence=1
    )

    await module._on_voice_state_update(
        "discord_voice_state",
        member=idle_three,
        before=disconnected,
        after=SimpleNamespace(channel=temporary),
    )

    temporary.edit.assert_awaited_once_with(
        name="#1 [Hangout]",
        reason="Bark Auto Voice: majority game changed",
    )


@pytest.mark.asyncio
async def test_presence_activity_change_refreshes_managed_channel_name():
    config = {
        "channel_name_template": "## [@@game_name@@]",
        "fallback_name": "Hangout",
    }
    ctx, guild, owner, _primary, temporary, *_ = _voice_fixture(config)
    owner.activities = [SimpleNamespace(name="Minecraft")]
    owner.voice = SimpleNamespace(channel=temporary)
    temporary.members = [owner]
    guild.get_member = lambda member_id: owner if member_id == owner.id else None
    module = AutoVoiceModule(ctx)
    module._managed_channels[temporary.id] = SimpleNamespace(
        guild_id=guild.id, owner_id=owner.id, sequence=1
    )

    await module._on_presence_update("discord_presence_update", before=owner, after=owner)

    temporary.edit.assert_awaited_once_with(
        name="#1 [Minecraft]",
        reason="Bark Auto Voice: majority game changed",
    )


@pytest.mark.asyncio
async def test_concurrent_majority_refreshes_only_rename_channel_once():
    config = {"channel_name_template": "## [@@game_name@@]"}
    ctx, guild, owner, _primary, temporary, *_ = _voice_fixture(config)
    owner.activities = [SimpleNamespace(name="Minecraft")]
    temporary.members = [owner]
    guild.get_member = lambda member_id: owner if member_id == owner.id else None

    async def delayed_edit(**_kwargs):
        await asyncio.sleep(0)

    temporary.edit = AsyncMock(side_effect=delayed_edit)
    module = AutoVoiceModule(ctx)
    module._managed_channels[temporary.id] = SimpleNamespace(
        guild_id=guild.id, owner_id=owner.id, sequence=1
    )

    await asyncio.gather(
        module._refresh_channel_name(temporary, config),
        module._refresh_channel_name(temporary, config),
    )

    assert temporary.edit.await_count == 1


@pytest.mark.asyncio
async def test_non_primary_join_does_not_create_channel():
    ctx, guild, member, primary, temporary, disconnected, joined_primary = _voice_fixture()
    module = AutoVoiceModule(ctx)
    ordinary = SimpleNamespace(id=777, guild=guild, members=[member])

    await module._on_voice_state_update(
        "discord_voice_state",
        member=member,
        before=disconnected,
        after=SimpleNamespace(channel=ordinary),
    )

    guild.create_voice_channel.assert_not_awaited()
    member.move_to.assert_not_awaited()


def _owner_interaction(member, channel):
    member.voice = SimpleNamespace(channel=channel)
    return SimpleNamespace(
        user=member,
        guild=member.guild,
        guild_id=member.guild.id,
        response=SimpleNamespace(send_message=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_owner_can_rename_managed_channel_when_enabled():
    ctx, guild, member, primary, temporary, *_ = _voice_fixture({"owner_can_rename": True})
    module = AutoVoiceModule(ctx)
    module._managed_channels[temporary.id] = SimpleNamespace(guild_id=guild.id, owner_id=member.id)
    interaction = _owner_interaction(member, temporary)

    command = module._make_voice_name_command()
    await command.callback(interaction, "Raid Room")

    temporary.edit.assert_awaited_once_with(
        name="Raid Room", reason="Bark Auto Voice: owner rename"
    )
    interaction.response.send_message.assert_awaited_once_with(
        "Channel renamed to **Raid Room**.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_owner_limit_command_honors_dashboard_switch():
    ctx, guild, member, primary, temporary, *_ = _voice_fixture({"owner_can_limit": False})
    module = AutoVoiceModule(ctx)
    module._managed_channels[temporary.id] = SimpleNamespace(guild_id=guild.id, owner_id=member.id)
    interaction = _owner_interaction(member, temporary)

    command = module._make_voice_limit_command()
    await command.callback(interaction, 4)

    temporary.edit.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once_with(
        "Changing the user limit is disabled for channel owners.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_owner_can_set_user_limit_when_enabled():
    ctx, guild, member, primary, temporary, *_ = _voice_fixture({"owner_can_limit": True})
    module = AutoVoiceModule(ctx)
    module._managed_channels[temporary.id] = SimpleNamespace(guild_id=guild.id, owner_id=member.id)
    interaction = _owner_interaction(member, temporary)

    command = module._make_voice_limit_command()
    await command.callback(interaction, 4)

    temporary.edit.assert_awaited_once_with(
        user_limit=4, reason="Bark Auto Voice: owner changed user limit"
    )


@pytest.mark.asyncio
async def test_owner_can_lock_managed_channel_when_enabled():
    ctx, guild, member, primary, temporary, *_ = _voice_fixture({"owner_can_lock": True})
    temporary.set_permissions = AsyncMock()
    module = AutoVoiceModule(ctx)
    module._managed_channels[temporary.id] = SimpleNamespace(guild_id=guild.id, owner_id=member.id)
    interaction = _owner_interaction(member, temporary)

    command = module._make_voice_lock_command()
    await command.callback(interaction)

    temporary.set_permissions.assert_awaited_once_with(
        guild.default_role,
        connect=False,
        reason="Bark Auto Voice: owner locked channel",
    )
    interaction.response.send_message.assert_awaited_once_with("Channel locked.", ephemeral=True)


@pytest.mark.asyncio
async def test_owner_can_unlock_managed_channel_when_enabled():
    ctx, guild, member, primary, temporary, *_ = _voice_fixture({"owner_can_lock": True})
    temporary.set_permissions = AsyncMock()
    module = AutoVoiceModule(ctx)
    module._managed_channels[temporary.id] = SimpleNamespace(guild_id=guild.id, owner_id=member.id)
    interaction = _owner_interaction(member, temporary)

    command = module._make_voice_unlock_command()
    await command.callback(interaction)

    temporary.set_permissions.assert_awaited_once_with(
        guild.default_role,
        connect=None,
        reason="Bark Auto Voice: owner unlocked channel",
    )
    interaction.response.send_message.assert_awaited_once_with("Channel unlocked.", ephemeral=True)
