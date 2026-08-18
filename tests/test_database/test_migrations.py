import ast
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from database.migrations import apply_migrations


def test_feature_model_guild_id_call_sites_are_explicitly_canonical_strings():
    """Discord.py exposes integer IDs, but feature FK values are strings."""
    root = Path(__file__).parents[2]
    model_names: set[str] = set()
    for model_path in (root / "database" / "models").glob("*.py"):
        tree = ast.parse(model_path.read_text())
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name == "DashboardGuildAccess":
                continue
            if any(
                isinstance(item, ast.AnnAssign)
                and isinstance(item.target, ast.Name)
                and item.target.id == "guild_id"
                for item in node.body
            ):
                model_names.add(node.name)

    violations: list[str] = []

    def is_canonical(value: ast.expr) -> bool:
        return (
            isinstance(value, ast.Constant)
            or (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "str"
            )
            or (isinstance(value, ast.Attribute) and value.attr == "discord_id")
        )

    for source_path in root.rglob("*.py"):
        if ".venv" in source_path.parts or source_path == Path(__file__):
            continue
        tree = ast.parse(source_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else ""
                )
                if called in model_names:
                    for keyword in node.keywords:
                        if keyword.arg == "guild_id" and not is_canonical(keyword.value):
                            violations.append(
                                f"{source_path.relative_to(root)}:{node.lineno} write"
                            )
            if (
                isinstance(node, ast.Compare)
                and isinstance(node.left, ast.Attribute)
                and node.left.attr == "guild_id"
                and isinstance(node.left.value, ast.Name)
                and node.left.value.id in model_names
            ):
                for comparator in node.comparators:
                    if not is_canonical(comparator):
                        violations.append(
                            f"{source_path.relative_to(root)}:{node.lineno} comparison"
                        )

    assert violations == []


@pytest.mark.asyncio
async def test_dashboard_guild_access_migration_upgrades_legacy_database(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    async with engine.begin() as connection:
        await connection.exec_driver_sql(
            "CREATE TABLE dashboard_users ("
            "id INTEGER PRIMARY KEY, discord_id VARCHAR(32) UNIQUE NOT NULL, "
            "username VARCHAR(64) NOT NULL, avatar_url VARCHAR(512) NOT NULL, "
            "role VARCHAR(16) NOT NULL, last_login DATETIME)"
        )
        await apply_migrations(connection)
        tables = {
            row[0]
            for row in (
                await connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            ).fetchall()
        }
        versions = {
            row[0]
            for row in (
                await connection.exec_driver_sql("SELECT version FROM schema_migrations")
            ).fetchall()
        }
        await connection.exec_driver_sql(
            "INSERT INTO dashboard_users "
            "(discord_id, username, avatar_url, role) VALUES "
            "('42', 'Cody', '', 'owner')"
        )
        await connection.exec_driver_sql(
            "INSERT INTO dashboard_guild_access "
            "(user_discord_id, guild_id, name) VALUES ('42', '100', 'Guild')"
        )
        await connection.exec_driver_sql("DELETE FROM dashboard_users WHERE discord_id = '42'")
        access_rows = (
            await connection.exec_driver_sql(
                "SELECT count(*) FROM dashboard_guild_access WHERE user_discord_id = '42'"
            )
        ).scalar_one()

    await engine.dispose()

    assert "dashboard_guild_access" in tables
    assert "0001_dashboard_guild_access" in versions
    assert "0003_dashboard_access_delete_trigger" in versions
    assert access_rows == 0


@pytest.mark.asyncio
async def test_module_config_migration_uses_exact_discord_guild_ids(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    async with engine.begin() as connection:
        await connection.exec_driver_sql(
            "CREATE TABLE dashboard_users ("
            "id INTEGER PRIMARY KEY, discord_id VARCHAR(32) UNIQUE NOT NULL, "
            "username VARCHAR(64) NOT NULL, avatar_url VARCHAR(512) NOT NULL, "
            "role VARCHAR(16) NOT NULL, last_login DATETIME)"
        )
        await connection.exec_driver_sql(
            "CREATE TABLE guilds (id INTEGER PRIMARY KEY, discord_id VARCHAR(32) UNIQUE NOT NULL)"
        )
        await connection.exec_driver_sql(
            "INSERT INTO guilds (id, discord_id) VALUES (1, '221627370375872512')"
        )
        await connection.exec_driver_sql(
            """
            CREATE TABLE module_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL REFERENCES guilds(id),
                module_name VARCHAR(64) NOT NULL,
                enabled BOOLEAN NOT NULL,
                priority INTEGER NOT NULL DEFAULT 100,
                config TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME,
                updated_at DATETIME,
                UNIQUE (guild_id, module_name)
            )
            """
        )
        await connection.exec_driver_sql(
            "INSERT INTO module_configs "
            "(guild_id, module_name, enabled, config, updated_at) VALUES "
            "(221627370375872500, 'logging', 0, '{\"old\": true}', '2026-01-01'), "
            "(221627370375872512, 'logging', 1, '{\"new\": true}', '2026-02-01'), "
            "(1, 'community', 1, '{}', '2026-03-01')"
        )

        await apply_migrations(connection)

        column_type = next(
            row[2]
            for row in (
                await connection.exec_driver_sql("PRAGMA table_info(module_configs)")
            ).fetchall()
            if row[1] == "guild_id"
        )
        rows = (
            await connection.exec_driver_sql(
                "SELECT guild_id, module_name, enabled, config "
                "FROM module_configs ORDER BY module_name"
            )
        ).fetchall()

    await engine.dispose()

    assert column_type == "VARCHAR(32)"
    assert rows == [
        ("221627370375872512", "community", 1, "{}"),
        ("221627370375872512", "logging", 1, '{"new": true}'),
    ]


@pytest.mark.asyncio
async def test_feature_guild_ids_are_normalized_to_discord_snowflake_strings(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    snowflake = 221627370375872512
    async with engine.begin() as connection:
        await connection.exec_driver_sql(
            "CREATE TABLE dashboard_users ("
            "id INTEGER PRIMARY KEY, discord_id VARCHAR(32) UNIQUE NOT NULL, "
            "username VARCHAR(64) NOT NULL, avatar_url VARCHAR(512) NOT NULL, "
            "role VARCHAR(16) NOT NULL, last_login DATETIME)"
        )
        await connection.exec_driver_sql(
            "CREATE TABLE guilds (id INTEGER PRIMARY KEY, discord_id VARCHAR(32) UNIQUE NOT NULL)"
        )
        await connection.exec_driver_sql(
            "INSERT INTO guilds (id, discord_id) VALUES (1, ?)",
            (str(snowflake),),
        )
        await connection.exec_driver_sql(
            "CREATE TABLE moderation_cases ("
            "id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL REFERENCES guilds(id), "
            "reason VARCHAR(100))"
        )
        await connection.exec_driver_sql(
            "INSERT INTO moderation_cases (id, guild_id, reason) VALUES "
            "(1, 1, 'internal'), (2, ?, 'snowflake')",
            (snowflake,),
        )

        await apply_migrations(connection)

        guild_id = (await connection.exec_driver_sql("SELECT id FROM guilds")).scalar_one()
        case_guild_ids = [
            row[0]
            for row in (
                await connection.exec_driver_sql(
                    "SELECT guild_id FROM moderation_cases ORDER BY id"
                )
            ).fetchall()
        ]
        column_type = (
            await connection.exec_driver_sql("PRAGMA table_info(moderation_cases)")
        ).fetchall()[1][2]
        foreign_key = (
            await connection.exec_driver_sql("PRAGMA foreign_key_list(moderation_cases)")
        ).one()

    await engine.dispose()

    assert guild_id == 1
    assert case_guild_ids == [str(snowflake), str(snowflake)]
    assert column_type == "VARCHAR(32)"
    assert foreign_key[2:5] == ("guilds", "guild_id", "discord_id")


@pytest.mark.asyncio
async def test_feature_guild_id_collision_keeps_newest_and_remaps_dependents(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'collision.db'}")
    snowflake = "221627370375872512"
    async with engine.begin() as connection:
        await connection.exec_driver_sql(
            "CREATE TABLE dashboard_users (id INTEGER PRIMARY KEY, discord_id VARCHAR(32) UNIQUE NOT NULL)"
        )
        await connection.exec_driver_sql(
            "CREATE TABLE guilds (id INTEGER PRIMARY KEY, discord_id VARCHAR(32) UNIQUE NOT NULL)"
        )
        await connection.exec_driver_sql(
            "INSERT INTO guilds (id, discord_id) VALUES (1, ?)", (snowflake,)
        )
        await connection.exec_driver_sql(
            "CREATE TABLE moderation_cases ("
            "id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL REFERENCES guilds(id), "
            "case_number INTEGER NOT NULL, reason TEXT, created_at DATETIME, "
            "UNIQUE (guild_id, case_number))"
        )
        await connection.exec_driver_sql(
            "CREATE TABLE warnings (id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL "
            "REFERENCES guilds(id), case_id INTEGER REFERENCES moderation_cases(id), reason TEXT)"
        )
        await connection.exec_driver_sql(
            "INSERT INTO moderation_cases VALUES "
            "(10, 1, 7, 'older legacy row', '2026-01-01'), "
            "(20, ?, 7, 'newest canonical row', '2026-02-01')",
            (snowflake,),
        )
        await connection.exec_driver_sql("INSERT INTO warnings VALUES (30, 1, 10, 'dependent')")

        await apply_migrations(connection)

        cases = (
            await connection.exec_driver_sql("SELECT id, guild_id, reason FROM moderation_cases")
        ).fetchall()
        warning = (
            await connection.exec_driver_sql("SELECT guild_id, case_id FROM warnings WHERE id = 30")
        ).one()
        violations = (await connection.exec_driver_sql("PRAGMA foreign_key_check")).fetchall()

    await engine.dispose()
    assert cases == [(20, snowflake, "newest canonical row")]
    assert warning == (snowflake, 20)
    assert violations == []


@pytest.mark.asyncio
async def test_unknown_feature_guild_id_rolls_back_entire_migration(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'unknown.db'}")
    async with engine.begin() as connection:
        await connection.exec_driver_sql(
            "CREATE TABLE dashboard_users (id INTEGER PRIMARY KEY, discord_id VARCHAR(32) UNIQUE NOT NULL)"
        )
        await connection.exec_driver_sql(
            "CREATE TABLE guilds (id INTEGER PRIMARY KEY, discord_id VARCHAR(32) UNIQUE NOT NULL)"
        )
        await connection.exec_driver_sql("INSERT INTO guilds VALUES (1, '221627370375872512')")
        await connection.exec_driver_sql(
            "CREATE TABLE audit_logs (id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL)"
        )
        await connection.exec_driver_sql("INSERT INTO audit_logs VALUES (1, 1)")
        await connection.exec_driver_sql(
            "CREATE TABLE warnings (id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL)"
        )
        await connection.exec_driver_sql("INSERT INTO warnings VALUES (1, 999)")

    with pytest.raises(RuntimeError, match=r"warnings contains unknown guild IDs: 999 \(1\)"):
        async with engine.begin() as connection:
            await apply_migrations(connection)

    async with engine.connect() as connection:
        assert (
            await connection.exec_driver_sql("SELECT guild_id FROM warnings")
        ).scalar_one() == 999
        audit_type = next(
            row[2]
            for row in (
                await connection.exec_driver_sql("PRAGMA table_info(audit_logs)")
            ).fetchall()
            if row[1] == "guild_id"
        )
        assert (
            await connection.exec_driver_sql("SELECT guild_id FROM audit_logs")
        ).scalar_one() == 1
        versions = {
            row[0]
            for row in (
                await connection.exec_driver_sql("SELECT version FROM schema_migrations")
            ).fetchall()
        }
    await engine.dispose()
    assert audit_type == "INTEGER"
    assert "0004_canonical_discord_guild_ids" not in versions


@pytest.mark.asyncio
async def test_canonical_feature_foreign_key_is_enforced(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fk.db'}")
    async with engine.connect() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        await connection.commit()
        async with connection.begin():
            await connection.exec_driver_sql(
                "CREATE TABLE dashboard_users (id INTEGER PRIMARY KEY, discord_id VARCHAR(32) UNIQUE NOT NULL)"
            )
            await connection.exec_driver_sql(
                "CREATE TABLE guilds (id INTEGER PRIMARY KEY, discord_id VARCHAR(32) UNIQUE NOT NULL)"
            )
            await connection.exec_driver_sql("INSERT INTO guilds VALUES (1, '123456789')")
            await connection.exec_driver_sql(
                "CREATE TABLE warnings (id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL REFERENCES guilds(id))"
            )
            await apply_migrations(connection)
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        assert (await connection.exec_driver_sql("PRAGMA foreign_keys")).scalar_one() == 1
        await connection.commit()

    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.exec_driver_sql(
                "INSERT INTO warnings (id, guild_id) VALUES (1, 'unknown')"
            )
    await engine.dispose()


@pytest.mark.asyncio
async def test_dashboard_guild_access_dedupes_and_enforces_unique(tmp_path):
    """Migration 0010 removes duplicate (user, guild) rows — keeping the
    strongest (owner first, then highest permissions, then newest) — and
    adds the unique index that legacy databases never received."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    async with engine.begin() as connection:
        # Legacy tables: no UNIQUE constraint, no roles column yet.
        await connection.exec_driver_sql(
            "CREATE TABLE dashboard_users ("
            "id INTEGER PRIMARY KEY, discord_id VARCHAR(32) UNIQUE NOT NULL, "
            "username VARCHAR(64) NOT NULL, avatar_url VARCHAR(512) NOT NULL, "
            "role VARCHAR(16) NOT NULL, last_login DATETIME)"
        )
        await connection.exec_driver_sql(
            "CREATE TABLE dashboard_guild_access ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_discord_id VARCHAR(32) NOT NULL, guild_id VARCHAR(32) NOT NULL, "
            "name VARCHAR(100) NOT NULL, icon_hash VARCHAR(128), "
            "permissions INTEGER NOT NULL DEFAULT 0, owner BOOLEAN NOT NULL DEFAULT 0, "
            "can_manage BOOLEAN NOT NULL DEFAULT 0)"
        )
        await connection.exec_driver_sql(
            "INSERT INTO dashboard_users (discord_id, username, avatar_url, role) "
            "VALUES ('42', 'Cody', '', 'owner')"
        )
        # Duplicate pairs: (42, 100) has a weak row + a strong owner row;
        # (42, 200) has two equal non-owner rows (newest id should win).
        await connection.exec_driver_sql(
            "INSERT INTO dashboard_guild_access "
            "(user_discord_id, guild_id, name, permissions, owner) VALUES "
            "('42', '100', 'Guild', 0, 0), "
            "('42', '100', 'Guild', 2147483647, 1), "
            "('42', '200', 'Guild2', 8, 0), "
            "('42', '200', 'Guild2', 8, 0)"
        )
        await apply_migrations(connection)

        rows = (
            await connection.exec_driver_sql(
                "SELECT user_discord_id, guild_id, owner, permissions, id "
                "FROM dashboard_guild_access ORDER BY guild_id"
            )
        ).fetchall()
        assert len(rows) == 2
        assert (rows[0][0], rows[0][1], rows[0][2]) == ("42", "100", 1)  # owner row kept
        assert rows[1][0] == "42" and rows[1][1] == "200" and rows[1][3] == 8
        assert rows[1][4] > 1  # newest id kept for the equal-pair group

        indexes = {
            row[1]
            for row in (
                await connection.exec_driver_sql(
                    'PRAGMA index_list("dashboard_guild_access")'
                )
            ).fetchall()
        }
        assert "uq_dashboard_user_guild" in indexes

        # The constraint is now enforced: inserting a duplicate must fail.
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            await connection.exec_driver_sql(
                "INSERT INTO dashboard_guild_access "
                "(user_discord_id, guild_id, name, permissions, owner) VALUES "
                "('42', '100', 'Guild', 0, 0)"
            )
    await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_channel_stats_from_reputation(tmp_path):
    """The 0016 migration rebuilds historical daily_channel_stats rows from
    reputation message events, so the Statistics page shows today/7d/30d data
    even right after an upgrade (the per-day recorder only starts on deploy)."""
    from database.migrations import _backfill_channel_stats_from_reputation

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'backfill.db'}")
    async with engine.connect() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        await connection.exec_driver_sql(
            "CREATE TABLE reputation_events ("
            "id INTEGER PRIMARY KEY, guild_id VARCHAR(32) NOT NULL, "
            "event_type VARCHAR(32) NOT NULL, channel_id VARCHAR(32), "
            "created_at DATETIME NOT NULL)"
        )
        await connection.exec_driver_sql(
            "CREATE TABLE daily_channel_stats ("
            "id INTEGER PRIMARY KEY, guild_id VARCHAR(32) NOT NULL, "
            "stat_date DATE NOT NULL, channel_id VARCHAR(32) NOT NULL, "
            "channel_name VARCHAR(120) NOT NULL DEFAULT '', "
            "message_count INTEGER NOT NULL DEFAULT 0, "
            "CONSTRAINT uq_daily_channel_day UNIQUE (guild_id, stat_date, channel_id))"
        )
        await connection.exec_driver_sql(
            "INSERT INTO reputation_events (guild_id, event_type, channel_id, created_at) VALUES "
            "('1', 'message', '100', '2026-08-14 10:00:00'), "
            "('1', 'message', '100', '2026-08-14 11:00:00'), "
            "('1', 'message', '100', '2026-08-14 12:00:00'), "
            "('1', 'message', '200', '2026-08-14 13:00:00'), "
            "('1', 'message', '200', '2026-08-15 13:00:00'), "
            "('1', 'reaction', '100', '2026-08-14 14:00:00'), "  # ignored: not a message
            "('1', 'message', NULL, '2026-08-14 15:00:00')"  # ignored: no channel
        )
        await _backfill_channel_stats_from_reputation(connection)
        await connection.commit()

        rows = (
            await connection.exec_driver_sql(
                "SELECT stat_date, channel_id, message_count "
                "FROM daily_channel_stats ORDER BY stat_date, channel_id"
            )
        ).fetchall()
        # channel 100 on 08-14 = 3; channel 200 on 08-14 = 1 and 08-15 = 1.
        assert ("2026-08-14", "100", 3) in rows
        assert ("2026-08-14", "200", 1) in rows
        assert ("2026-08-15", "200", 1) in rows
        assert len(rows) == 3, f"expected 3 backfilled rows, got {rows}"
    await engine.dispose()


async def test_add_reputation_tier_purpose(tmp_path):
    """The 0017 migration adds a purpose column to reputation_tiers.

    It is guarded by a PRAGMA probe so it tolerates both fresh schemas (where
    create_all already has the column) and legacy ones (that need the ALTER).
    """
    from database.migrations import _add_reputation_tier_purpose

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tier_purpose.db'}")
    async with engine.connect() as connection:
        # Legacy schema without the purpose column.
        await connection.exec_driver_sql(
            "CREATE TABLE reputation_tiers ("
            "id INTEGER PRIMARY KEY, guild_id VARCHAR(32) NOT NULL, "
            "name VARCHAR(64) NOT NULL, symbol VARCHAR(16) NOT NULL, "
            "min_score FLOAT NOT NULL DEFAULT 0, min_level INTEGER NOT NULL DEFAULT 0, "
            "color_hex VARCHAR(7) NOT NULL DEFAULT '#99aab5', "
            "role_id VARCHAR(32), assign_role BOOLEAN NOT NULL DEFAULT 0, "
            "is_default BOOLEAN NOT NULL DEFAULT 0, sort_order INTEGER NOT NULL DEFAULT 0)"
        )
        await _add_reputation_tier_purpose(connection)
        await connection.commit()

        columns = {
            row[1]
            for row in (
                await connection.exec_driver_sql(
                    'PRAGMA table_info("reputation_tiers")'
                )
            ).fetchall()
        }
        assert "purpose" in columns, f"purpose column missing; columns={columns}"

        # Idempotent: running again must not error when the column exists.
        await _add_reputation_tier_purpose(connection)
    await engine.dispose()

