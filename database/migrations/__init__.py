"""Small, ordered database migrations for deployed Bark databases."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Sequence

from sqlalchemy.ext.asyncio import AsyncConnection

MigrationAction = Sequence[str] | Callable[[AsyncConnection], Awaitable[None]]
Migration = tuple[str, MigrationAction]


async def _normalize_module_config_guild_ids(connection: AsyncConnection) -> None:
    table_exists = (
        await connection.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='module_configs'"
        )
    ).first()
    if table_exists is None:
        return

    guild_rows = (await connection.exec_driver_sql("SELECT id, discord_id FROM guilds")).fetchall()
    by_internal_id = {str(row[0]): str(row[1]) for row in guild_rows}
    discord_ids = {str(row[1]) for row in guild_rows}

    def normalize(raw_id) -> str:
        value = str(raw_id)
        # An exact Discord ID is authoritative.  This ordering also handles
        # the (valid, if unusual) case where a snowflake equals another
        # guild's surrogate integer ID.
        if value in discord_ids:
            return value
        if value in by_internal_id:
            return by_internal_id[value]
        # Migration 0002 predates the strict canonical FK migration and
        # repairs the known JavaScript-number rounding damage in legacy
        # module-config snowflakes only.
        if value.isdigit() and discord_ids:
            closest = min(discord_ids, key=lambda candidate: abs(int(candidate) - int(value)))
            if abs(int(closest) - int(value)) <= 1024:
                return closest
        return value

    rows = (
        await connection.exec_driver_sql(
            "SELECT id, guild_id, module_name, enabled, priority, config, "
            "created_at, updated_at FROM module_configs"
        )
    ).fetchall()
    selected = {}
    for row in sorted(rows, key=lambda item: (str(item[7] or item[6] or ""), item[0])):
        guild_id = normalize(row[1])
        selected[(guild_id, row[2])] = (
            row[0],
            guild_id,
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
            row[7],
        )

    await connection.exec_driver_sql(
        """
        CREATE TABLE module_configs_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id VARCHAR(32) NOT NULL,
            module_name VARCHAR(64) NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT 1,
            priority INTEGER NOT NULL DEFAULT 100,
            config TEXT NOT NULL DEFAULT '{}',
            created_at DATETIME,
            updated_at DATETIME,
            UNIQUE (guild_id, module_name)
        )
        """
    )
    if selected:
        await connection.exec_driver_sql(
            "INSERT INTO module_configs_new "
            "(id, guild_id, module_name, enabled, priority, config, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            list(selected.values()),
        )
    await connection.exec_driver_sql("DROP TABLE module_configs")
    await connection.exec_driver_sql("ALTER TABLE module_configs_new RENAME TO module_configs")
    await connection.exec_driver_sql(
        "CREATE INDEX ix_module_configs_guild_id ON module_configs (guild_id)"
    )


async def _canonicalize_feature_guild_ids(connection: AsyncConnection) -> None:
    """Store exact Discord snowflakes in every feature table guild_id."""
    guilds_exists = (
        await connection.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='guilds'"
        )
    ).first()
    if guilds_exists is None:
        return

    guild_rows = (await connection.exec_driver_sql("SELECT id, discord_id FROM guilds")).fetchall()
    internal_to_discord = {str(row[0]): str(row[1]) for row in guild_rows}
    discord_ids = {str(row[1]) for row in guild_rows}

    def normalize(value: object) -> str:
        text = str(value)
        if text in discord_ids:
            return text
        if text in internal_to_discord:
            return internal_to_discord[text]
        raise RuntimeError(f"Unresolvable guild_id {text!r}")

    table_rows = (
        await connection.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ).fetchall()
    excluded = {"guilds", "dashboard_guild_access", "schema_migrations"}
    for table_name, create_sql in table_rows:
        if table_name in excluded or not create_sql:
            continue
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name):
            raise RuntimeError(f"Unsafe SQLite table name {table_name!r}")
        table_info = (
            await connection.exec_driver_sql(f'PRAGMA table_info("{table_name}")')
        ).fetchall()
        columns = [row[1] for row in table_info]
        if "guild_id" not in columns:
            continue

        # table_name regex-validated above; values never interpolated
        rows = (
            await connection.exec_driver_sql(f'SELECT * FROM "{table_name}"')  # nosec B608
        ).fetchall()
        guild_index = columns.index("guild_id")
        normalized_rows: list[tuple] = []
        unknown: dict[str, int] = {}
        for row in rows:
            values = list(row)
            try:
                values[guild_index] = normalize(values[guild_index])
            except RuntimeError:
                unknown_value = str(values[guild_index])
                unknown[unknown_value] = unknown.get(unknown_value, 0) + 1
                continue
            normalized_rows.append(tuple(values))
        if unknown:
            details = ", ".join(f"{key} ({count})" for key, count in sorted(unknown.items()))
            raise RuntimeError(f"{table_name} contains unknown guild IDs: {details}")

        # Resolve legacy internal-ID/snowflake duplicates deterministically by
        # retaining the newest row and remapping dependent foreign keys.
        retained = set(range(len(normalized_rows)))
        id_position = next(
            (index for index, info in enumerate(table_info) if info[5] == 1),
            None,
        )
        remapped_ids: list[tuple[object, object]] = []

        def row_rank(row: tuple) -> tuple:
            values = []
            for name in ("updated_at", "created_at"):
                values.append(row[columns.index(name)] or "" if name in columns else "")
            values.append(row[id_position] if id_position is not None else 0)
            return tuple(values)

        for index_row in (
            await connection.exec_driver_sql(f'PRAGMA index_list("{table_name}")')
        ).fetchall():
            if not index_row[2]:
                continue
            index_name = index_row[1]
            index_columns = [
                row[2]
                for row in (
                    await connection.exec_driver_sql(f'PRAGMA index_info("{index_name}")')
                ).fetchall()
            ]
            if "guild_id" not in index_columns:
                continue
            positions = [columns.index(name) for name in index_columns]
            groups: dict[tuple, list[int]] = {}
            for row_index in retained:
                group_key = tuple(normalized_rows[row_index][pos] for pos in positions)
                groups.setdefault(group_key, []).append(row_index)
            for group in groups.values():
                if len(group) < 2:
                    continue
                keep = max(group, key=lambda index: row_rank(normalized_rows[index]))
                for drop in group:
                    if drop == keep:
                        continue
                    retained.discard(drop)
                    if id_position is not None:
                        remapped_ids.append(
                            (
                                normalized_rows[drop][id_position],
                                normalized_rows[keep][id_position],
                            )
                        )

        if len(retained) != len(normalized_rows):
            normalized_rows = [
                row for index, row in enumerate(normalized_rows) if index in retained
            ]
            primary_name = columns[id_position] if id_position is not None else None
            if primary_name and remapped_ids:
                for child_name, _child_sql in table_rows:
                    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", child_name):
                        continue
                    for foreign_key in (
                        await connection.exec_driver_sql(f'PRAGMA foreign_key_list("{child_name}")')
                    ).fetchall():
                        if foreign_key[2] != table_name or foreign_key[4] != primary_name:
                            continue
                        child_column = foreign_key[3]
                        for old_id, new_id in remapped_ids:
                            # child_name regex-validated; column from SQLite schema
                            await connection.exec_driver_sql(
                                f'UPDATE "{child_name}" SET "{child_column}" = ? '  # nosec B608
                                f'WHERE "{child_column}" = ?',
                                (new_id, old_id),
                            )

        foreign_keys = (
            await connection.exec_driver_sql(f'PRAGMA foreign_key_list("{table_name}")')
        ).fetchall()
        already_canonical = (
            any(
                row[2] == "guilds" and row[3] == "guild_id" and row[4] == "discord_id"
                for row in foreign_keys
            )
            and "CHAR" in str(table_info[guild_index][2]).upper()
        )
        if already_canonical and all(
            tuple(row) == normalized_rows[i] for i, row in enumerate(rows)
        ):
            continue

        dependent_sql = [
            row[0]
            for row in (
                await connection.exec_driver_sql(
                    "SELECT sql FROM sqlite_master WHERE tbl_name = ? "
                    "AND type IN ('index', 'trigger') AND sql IS NOT NULL",
                    (table_name,),
                )
            ).fetchall()
        ]
        temp_name = f"{table_name}__canonical"
        rebuilt_sql = re.sub(
            r"(?i)([\"`\[]?guild_id[\"`\]]?\s+)"
            r"(?:INTEGER|BIGINT|TEXT|VARCHAR\s*\(\s*\d+\s*\))",
            r"\1VARCHAR(32)",
            create_sql,
            count=1,
        )
        rebuilt_sql = re.sub(
            r"(?i)REFERENCES\s+[\"`\[]?guilds[\"`\]]?\s*\(\s*[\"`\[]?id[\"`\]]?\s*\)",
            "REFERENCES guilds(discord_id)",
            rebuilt_sql,
        )
        has_guild_fk = any(row[2] == "guilds" and row[3] == "guild_id" for row in foreign_keys)
        if not has_guild_fk:
            close = rebuilt_sql.rfind(")")
            rebuilt_sql = (
                rebuilt_sql[:close]
                + ", FOREIGN KEY(guild_id) REFERENCES guilds(discord_id)"
                + rebuilt_sql[close:]
            )
        rebuilt_sql = re.sub(
            rf"(?i)^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`\[]?{re.escape(table_name)}[\"`\]]?",
            f'CREATE TABLE "{temp_name}"',
            rebuilt_sql,
            count=1,
        )
        await connection.exec_driver_sql(f'DROP TABLE IF EXISTS "{temp_name}"')
        await connection.exec_driver_sql(rebuilt_sql)
        if normalized_rows:
            quoted_columns = ", ".join(f'"{name}"' for name in columns)
            placeholders = ", ".join("?" for _ in columns)
            # temp_name/columns validated + quoted; values parameterized
            await connection.exec_driver_sql(
                f'INSERT INTO "{temp_name}" ({quoted_columns}) VALUES ({placeholders})',  # nosec B608
                normalized_rows,
            )
        await connection.exec_driver_sql(f'DROP TABLE "{table_name}"')
        await connection.exec_driver_sql(f'ALTER TABLE "{temp_name}" RENAME TO "{table_name}"')
        for sql in dependent_sql:
            await connection.exec_driver_sql(sql)

    violations = (await connection.exec_driver_sql("PRAGMA foreign_key_check")).fetchall()
    if violations:
        raise RuntimeError(
            f"Foreign-key violations remain after guild migration: {violations[:10]}"
        )


async def _add_post_delivery_state(connection: AsyncConnection) -> None:
    table_exists = (
        await connection.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='post_messages'"
        )
    ).first()
    if table_exists is None:
        return
    columns = {
        row[1]
        for row in (await connection.exec_driver_sql("PRAGMA table_info(post_messages)")).fetchall()
    }
    additions = {
        "retry_count": "INTEGER NOT NULL DEFAULT 0",
        "failed": "BOOLEAN NOT NULL DEFAULT 0",
        "last_attempt": "DATETIME",
    }
    for name, declaration in additions.items():
        if name not in columns:
            await connection.exec_driver_sql(
                f"ALTER TABLE post_messages ADD COLUMN {name} {declaration}"
            )


async def _migrate_logging_config(connection: AsyncConnection) -> None:
    """Copy legacy LogConfig events into canonical ModuleConfig JSON."""
    tables = {
        row[0]
        for row in (
            await connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'")
        ).fetchall()
    }
    if not {"log_configs", "module_configs"}.issubset(tables):
        return
    legacy_rows = (
        await connection.exec_driver_sql(
            "SELECT guild_id, event_type, channel_id, enabled FROM log_configs"
        )
    ).fetchall()
    for guild_id, event_type, channel_id, enabled in legacy_rows:
        row = (
            await connection.exec_driver_sql(
                "SELECT id, config FROM module_configs "
                "WHERE guild_id = ? AND module_name = 'logging'",
                (str(guild_id),),
            )
        ).first()
        config = json.loads(row[1] or "{}") if row else {}
        if event_type in config:
            continue
        config[event_type] = {
            "channel_id": str(channel_id),
            "enabled": bool(enabled),
        }
        if row:
            await connection.exec_driver_sql(
                "UPDATE module_configs SET config = ? WHERE id = ?",
                (json.dumps(config), row[0]),
            )
        else:
            await connection.exec_driver_sql(
                "INSERT INTO module_configs "
                "(guild_id, module_name, enabled, priority, config, created_at, updated_at) "
                "VALUES (?, 'logging', 1, 100, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (str(guild_id), json.dumps(config)),
            )


async def _add_fk_indexes(connection: AsyncConnection) -> None:
    """Add indexes on hot foreign-key columns, tolerating legacy schemas.

    CREATE INDEX IF NOT EXISTS still raises when the target table or column is
    absent, so probe sqlite_master first and skip missing ones.
    """
    wanted = [
        ("moderation_cases", "guild_id"),
        ("moderation_cases", "target_id"),
        ("warnings", "guild_id"),
        ("user_notes", "guild_id"),
        ("audit_logs", "guild_id"),
        ("audit_logs", "actor_id"),
        ("audit_logs", "target_id"),
        ("file_attachments", "guild_id"),
        ("file_attachments", "channel_id"),
        ("automod_configs", "guild_id"),
        ("log_configs", "guild_id"),
        ("log_configs", "channel_id"),
        ("voice_sessions", "guild_id"),
        ("voice_sessions", "channel_id"),
        ("reputation_events", "channel_id"),
        ("role_assignments", "rule_id"),
    ]
    for table, column in wanted:
        probe = await connection.exec_driver_sql(
            "SELECT 1 FROM pragma_table_info(?) WHERE name = ?",
            (table, column),
        )
        if probe.first() is None:
            continue
        index_name = f"ix_{table}_{column}"
        await connection.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({column})"
        )


async def _add_dashboard_guild_access_roles(connection: AsyncConnection) -> None:
    """Add the ``roles`` snapshot column to ``dashboard_guild_access``.

    ``create_all`` already includes the column on fresh databases, so the
    ALTER is guarded by a PRAGMA column probe.
    """
    columns = {
        row[1]
        for row in (
            await connection.exec_driver_sql('PRAGMA table_info("dashboard_guild_access")')
        ).fetchall()
    }
    if "roles" not in columns:
        await connection.exec_driver_sql(
            "ALTER TABLE dashboard_guild_access "
            "ADD COLUMN roles VARCHAR(512) NOT NULL DEFAULT ''"
        )


MIGRATIONS: tuple[Migration, ...] = (
    (
        "0001_dashboard_guild_access",
        (
            """
            CREATE TABLE IF NOT EXISTS dashboard_guild_access (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_discord_id VARCHAR(32) NOT NULL,
                guild_id VARCHAR(32) NOT NULL,
                name VARCHAR(100) NOT NULL,
                icon_hash VARCHAR(128),
                permissions INTEGER NOT NULL DEFAULT 0,
                owner BOOLEAN NOT NULL DEFAULT 0,
                can_manage BOOLEAN NOT NULL DEFAULT 0,
                CONSTRAINT uq_dashboard_user_guild
                    UNIQUE (user_discord_id, guild_id),
                FOREIGN KEY(user_discord_id)
                    REFERENCES dashboard_users (discord_id) ON DELETE CASCADE
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_dashboard_guild_access_user_discord_id ON dashboard_guild_access (user_discord_id)",
            "CREATE INDEX IF NOT EXISTS ix_dashboard_guild_access_guild_id ON dashboard_guild_access (guild_id)",
        ),
    ),
    ("0002_module_config_discord_guild_ids", _normalize_module_config_guild_ids),
    (
        "0003_dashboard_access_delete_trigger",
        (
            """
            CREATE TRIGGER IF NOT EXISTS delete_dashboard_guild_access
            AFTER DELETE ON dashboard_users
            BEGIN
                DELETE FROM dashboard_guild_access
                WHERE user_discord_id = OLD.discord_id;
            END
            """,
        ),
    ),
    ("0004_canonical_discord_guild_ids", _canonicalize_feature_guild_ids),
    ("0005_post_delivery_state", _add_post_delivery_state),
    ("0006_canonical_logging_config", _migrate_logging_config),
    (
        "0007_fk_indexes",
        _add_fk_indexes,
    ),
    (
        "0008_instance_invites",
        (
            """
            CREATE TABLE IF NOT EXISTS instance_invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_hash VARCHAR(64) NOT NULL UNIQUE,
                created_by_discord_id VARCHAR(32) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                redeemed_at DATETIME,
                redeemed_by_discord_id VARCHAR(32),
                revoked_at DATETIME,
                note TEXT NOT NULL DEFAULT ''
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_instance_invites_token_hash ON instance_invites (token_hash)",
            "CREATE INDEX IF NOT EXISTS ix_instance_invites_expires_at ON instance_invites (expires_at)",
            """
            CREATE TABLE IF NOT EXISTS instance_access (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_user_id VARCHAR(32) NOT NULL UNIQUE,
                role VARCHAR(16) NOT NULL DEFAULT 'admin',
                granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                revoked_at DATETIME
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_instance_access_discord_user_id ON instance_access (discord_user_id)",
        ),
    ),
    (
        "0009_dashboard_guild_access_roles",
        _add_dashboard_guild_access_roles,
    ),
)


async def apply_migrations(connection: AsyncConnection) -> None:
    """Apply every pending migration exactly once."""
    await connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(128) PRIMARY KEY,
            applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    applied = {
        row[0]
        for row in (
            await connection.exec_driver_sql("SELECT version FROM schema_migrations")
        ).fetchall()
    }
    for version, action in MIGRATIONS:
        if version in applied:
            continue
        if callable(action):
            await action(connection)
        else:
            for statement in action:
                await connection.exec_driver_sql(statement)
        await connection.exec_driver_sql(
            "INSERT INTO schema_migrations (version) VALUES (?)",
            (version,),
        )
