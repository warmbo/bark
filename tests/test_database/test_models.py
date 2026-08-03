"""
Tests for database models and engine.
"""

import pytest
from sqlalchemy import func, select

from database.engine import close_db, get_engine, get_session_factory, init_db, session_scope
from database.models.automod import AutoModConfig
from database.models.guild import Guild, GuildSetting
from database.models.logging import LogConfig
from database.models.moderation import AuditLog, ModerationCase
from database.models.module import ModuleConfig
from database.models.permissions import DashboardUser


@pytest.fixture
async def db():
    """Initialize test database."""
    await init_db()
    yield
    await close_db()


@pytest.mark.asyncio
async def test_create_guild(db):
    """Test creating a guild record."""
    async with session_scope() as session:
        guild = Guild(
            discord_id="123456789",
            name="Test Guild",
            owner_id="987654321",
            prefix="!",
        )
        session.add(guild)
        await session.commit()

    async with session_scope() as session:
        result = await session.execute(select(Guild).where(Guild.discord_id == "123456789"))
        saved = result.scalar_one()
        assert saved.name == "Test Guild"
        assert saved.owner_id == "987654321"
        assert saved.prefix == "!"


@pytest.mark.asyncio
async def test_close_db_clears_engine_and_session_factory(db):
    engine_before = get_engine()
    factory_before = get_session_factory()

    await close_db()

    assert get_engine() is not engine_before
    assert get_session_factory() is not factory_before


@pytest.mark.asyncio
async def test_create_guild_setting(db):
    """Test guild settings."""
    async with session_scope() as session:
        guild = Guild(discord_id="s1", name="Settings Test")
        session.add(guild)
        await session.flush()

        setting = GuildSetting(guild_id=guild.discord_id, key="mod_role", value="123")
        session.add(setting)
        await session.commit()

    async with session_scope() as session:
        result = await session.execute(
            select(GuildSetting).where(
                GuildSetting.key == "mod_role",
                GuildSetting.guild_id == guild.discord_id,
            )
        )
        saved = result.scalar_one()
        assert saved.value == "123"


@pytest.mark.asyncio
async def test_create_moderation_case(db):
    """Test creating a moderation case with auto-incrementing case number."""
    from sqlalchemy import select

    async with session_scope() as session:
        guild = Guild(discord_id="m1", name="Mod Test")
        session.add(guild)
        await session.flush()

        # First case
        result = await session.execute(
            select(func.coalesce(func.max(ModerationCase.case_number), 0) + 1).where(
                ModerationCase.guild_id == guild.discord_id
            )
        )
        case1 = ModerationCase(
            guild_id=guild.discord_id,
            case_number=result.scalar(),
            action_type="warn",
            target_id="111",
            target_tag="User#1111",
            moderator_id="222",
            moderator_tag="Mod#2222",
            reason="Test warn",
        )
        session.add(case1)
        await session.commit()

    assert case1.case_number == 1


@pytest.mark.asyncio
async def test_module_config(db):
    """Test module configuration."""
    async with session_scope() as session:
        guild = Guild(discord_id="mc1", name="Module Config Test")
        session.add(guild)
        await session.flush()

        config = ModuleConfig(
            guild_id=guild.discord_id,
            module_name="moderation",
            enabled=True,
            priority=100,
            config='{"log_channel": "123"}',
        )
        session.add(config)
        await session.commit()

    async with session_scope() as session:
        result = await session.execute(
            select(ModuleConfig).where(
                ModuleConfig.guild_id == guild.discord_id,
                ModuleConfig.module_name == "moderation",
            )
        )
        saved = result.scalar_one()
        assert saved.enabled is True
        assert saved.priority == 100


@pytest.mark.asyncio
async def test_log_config(db):
    """Test logging configuration."""
    async with session_scope() as session:
        guild = Guild(discord_id="log1", name="Log Test")
        session.add(guild)
        await session.flush()

        log_cfg = LogConfig(
            guild_id=guild.discord_id,
            event_type="message_delete",
            channel_id="555",
            enabled=True,
        )
        session.add(log_cfg)
        await session.commit()

    async with session_scope() as session:
        result = await session.execute(
            select(LogConfig).where(
                LogConfig.guild_id == guild.discord_id,
                LogConfig.event_type == "message_delete",
            )
        )
        saved = result.scalar_one()
        assert saved.channel_id == "555"


@pytest.mark.asyncio
async def test_automod_config(db):
    """Test AutoMod configuration."""
    async with session_scope() as session:
        guild = Guild(discord_id="am1", name="AutoMod Test")
        session.add(guild)
        await session.flush()

        am = AutoModConfig(
            guild_id=guild.discord_id,
            rule_type="spam",
            enabled=True,
            threshold=5,
            action="warn",
            duration=10,
        )
        session.add(am)
        await session.commit()

    async with session_scope() as session:
        result = await session.execute(
            select(AutoModConfig).where(
                AutoModConfig.guild_id == guild.discord_id,
                AutoModConfig.rule_type == "spam",
            )
        )
        saved = result.scalar_one()
        assert saved.threshold == 5
        assert saved.action == "warn"


@pytest.mark.asyncio
async def test_dashboard_user(db):
    """Test dashboard user model."""
    async with session_scope() as session:
        user = DashboardUser(
            discord_id="123",
            username="TestAdmin",
            role="admin",
        )
        session.add(user)
        await session.commit()

    async with session_scope() as session:
        result = await session.execute(
            select(DashboardUser).where(DashboardUser.discord_id == "123")
        )
        saved = result.scalar_one()
        assert saved.role == "admin"


@pytest.mark.asyncio
async def test_audit_log(db):
    """Test audit log creation."""
    import json

    async with session_scope() as session:
        guild = Guild(discord_id="audit1", name="Audit Test")
        session.add(guild)
        await session.flush()

        log = AuditLog(
            guild_id=guild.discord_id,
            action="warn",
            actor_id="111",
            target_id="222",
            details=json.dumps({"reason": "testing"}),
        )
        session.add(log)
        await session.commit()

    async with session_scope() as session:
        result = await session.execute(
            select(AuditLog).where(AuditLog.guild_id == guild.discord_id)
        )
        saved = result.scalar_one()
        assert saved.action == "warn"
