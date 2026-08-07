# Data Model

All models use SQLAlchemy 2.0 declarative mapping with async sessions. Source: `database/models/`. The Base is defined in `database/engine.py`. All models register with `Base.metadata` via `database/models/__init__.py`.

## Guild

**Table:** `guilds`  — **File:** `database/models/guild.py`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | Internal ID |
| `discord_id` | String(32) | UNIQUE, NOT NULL, indexed | Discord guild snowflake |
| `name` | String(128) | NOT NULL, default "Unknown" | |
| `owner_id` | String(32) | NOT NULL, default "" | |
| `prefix` | String(16) | NOT NULL, default "!" | Bot command prefix |
| `locale` | String(8) | NOT NULL, default "en-US" | |
| `created_at` | DateTime | NOT NULL, default utcnow | |
| `updated_at` | DateTime | NOT NULL, onupdate utcnow | |

**Relationships:** settings, moderation_cases, log_configs, automod_configs, warnings, user_notes, audit_logs, rulesets, word_lists (all cascade delete-orphan)

## GuildSetting

**Table:** `guild_settings`  — **File:** `database/models/guild.py`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `guild_id` | String(32) | FK → guilds.discord_id, NOT NULL | |
| `key` | String(64) | NOT NULL | Setting name |
| `value` | Text | NOT NULL, default "" | Setting value |

**Constraints:** UNIQUE(guild_id, key)

## ModuleConfig

**Table:** `module_configs`  — **File:** `database/models/module.py`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `guild_id` | String(32) | FK → guilds.discord_id, NOT NULL, indexed | |
| `module_name` | String(64) | NOT NULL | e.g. "moderation", "logging" |
| `enabled` | Boolean | NOT NULL, default False | Per-guild enable/disable |
| `priority` | Integer | NOT NULL, default 100 | Module execution priority |
| `config` | Text | NOT NULL, default "{}" | JSON blob of module settings |
| `created_at` | DateTime | NOT NULL, default utcnow | |
| `updated_at` | DateTime | NOT NULL, onupdate utcnow | |

**Constraints:** UNIQUE(guild_id, module_name)

## ModerationCase

**Table:** `moderation_cases`  — **File:** `database/models/moderation.py`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `guild_id` | String(32) | FK → guilds.discord_id, NOT NULL | |
| `case_number` | Integer | NOT NULL | Sequential per-guild |
| `action_type` | String(32) | NOT NULL | warn, timeout, kick, ban, unban |
| `target_id` | String(32) | NOT NULL | Discord user ID |
| `target_tag` | String(64) | NOT NULL, default "Unknown#0000" | Discord username+discrim |
| `moderator_id` | String(32) | NOT NULL | |
| `moderator_tag` | String(64) | NOT NULL, default "Unknown#0000" | |
| `reason` | Text | NOT NULL, default "" | |
| `duration` | Integer | NULL | Minutes (for timeout) |
| `created_at` | DateTime | NOT NULL, default utcnow | |
| `resolved` | Boolean | NOT NULL, default False | Soft-delete flag |
| `resolved_at` | DateTime | NULL | When soft-deleted |

**Constraints:** UNIQUE(guild_id, case_number)

## Warning

**Table:** `warnings`  — **File:** `database/models/moderation.py`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `guild_id` | String(32) | FK → guilds.discord_id, NOT NULL | |
| `case_id` | Integer | FK → moderation_cases.id, SET NULL, indexed | Linked case (optional) |
| `user_id` | String(32) | NOT NULL, indexed | |
| `moderator_id` | String(32) | NOT NULL | |
| `reason` | Text | NOT NULL, default "" | |
| `created_at` | DateTime | NOT NULL, default utcnow | |
| `active` | Boolean | NOT NULL, default True | False = cleared/deactivated |

## UserNote

**Table:** `user_notes`  — **File:** `database/models/moderation.py`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `guild_id` | String(32) | FK → guilds.discord_id, NOT NULL | |
| `user_id` | String(32) | NOT NULL, indexed | Discord user ID |
| `author_id` | String(32) | NOT NULL | Dashboard user or "dashboard" |
| `content` | Text | NOT NULL | Max 2000 chars (API-enforced) |
| `created_at` | DateTime | NOT NULL, default utcnow | |

## AuditLog

**Table:** `audit_logs`  — **File:** `database/models/moderation.py`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `guild_id` | String(32) | FK → guilds.discord_id, NOT NULL | |
| `action` | String(64) | NOT NULL, indexed | e.g. warn, ban, unban, member_update |
| `actor_id` | String(32) | NOT NULL | Who performed the action |
| `target_id` | String(32) | NULL | Who was acted upon |
| `details` | Text | NOT NULL, default "{}" | JSON blob with actor_tag, target_tag, timestamp, extras |
| `created_at` | DateTime | NOT NULL, default utcnow | |

## LogConfig

**Table:** `log_configs`  — **File:** `database/models/logging.py`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `guild_id` | String(32) | FK → guilds.discord_id, NOT NULL | |
| `event_type` | String(64) | NOT NULL | e.g. message_delete, member_join |
| `channel_id` | String(32) | NOT NULL | Discord channel ID |
| `enabled` | Boolean | NOT NULL, default True | |

**Constraints:** UNIQUE(guild_id, event_type)

## AutoModConfig

**Table:** `automod_configs`  — **File:** `database/models/automod.py`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `guild_id` | String(32) | FK → guilds.discord_id, NOT NULL | |
| `rule_type` | String(32) | NOT NULL | spam, invite, mention |
| `enabled` | Boolean | NOT NULL, default False | |
| `threshold` | Integer | NOT NULL, default 5 | Trigger count |
| `action` | String(16) | NOT NULL, default "warn" | warn, timeout, delete |
| `duration` | Integer | NOT NULL, default 10 | Minutes |
| `ignored_roles` | Text | NOT NULL, default "[]" | JSON array of role IDs |
| `ignored_channels` | Text | NOT NULL, default "[]" | JSON array of channel IDs |

**Constraints:** UNIQUE(guild_id, rule_type)

## RuleSet

**Table:** `rulesets`  — **File:** `database/models/ruleset.py`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `guild_id` | String(32) | FK → guilds.discord_id, NOT NULL, indexed | |
| `name` | String(64) | NOT NULL, default "Default" | Human-readable name |
| `enabled` | Boolean | NOT NULL, default True | |
| `priority` | Integer | NOT NULL, default 100 | Execution order |
| `ignored_roles` | Text | NOT NULL, default "[]" | JSON array |
| `require_roles` | Text | NOT NULL, default "[]" | JSON array |
| `require_all_roles` | Boolean | NOT NULL, default False | AND vs OR for require_roles |
| `ignored_channels` | Text | NOT NULL, default "[]" | JSON array |
| `active_channels` | Text | NOT NULL, default "[]" | JSON array |
| `ignored_categories` | Text | NOT NULL, default "[]" | JSON array |
| `active_categories` | Text | NOT NULL, default "[]" | JSON array |
| `account_age_minutes_min` | Integer | NOT NULL, default 0 | 0 = no check |
| `account_age_minutes_max` | Integer | NOT NULL, default 0 | 0 = no check |
| `member_duration_minutes_min` | Integer | NOT NULL, default 0 | 0 = no check |
| `member_duration_minutes_max` | Integer | NOT NULL, default 0 | 0 = no check |
| `only_bots` | Boolean | NOT NULL, default False | |
| `ignore_bots` | Boolean | NOT NULL, default True | |
| `check_new_messages` | Boolean | NOT NULL, default True | |
| `check_edited_messages` | Boolean | NOT NULL, default False | |
| `created_at` | DateTime | NOT NULL, default utcnow | |

**Constraints:** UNIQUE(guild_id, name) — **Relationships:** rules (cascade delete-orphan), guild

## Rule

**Table:** `rules`  — **File:** `database/models/ruleset.py`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `ruleset_id` | Integer | FK → rulesets.id, CASCADE, indexed | |
| `enabled` | Boolean | NOT NULL, default True | |
| `priority` | Integer | NOT NULL, default 50 | |
| `trigger_type` | String(32) | NOT NULL | spam, invite, mention, word_denylist, regex_match, scam_link, etc. |
| `trigger_config` | Text | NOT NULL, default "{}" | JSON: threshold, window_seconds, word_list_id, pattern, etc. |
| `effect_type` | String(24) | NOT NULL, default "warn" | warn, delete, timeout, kick, ban, mute, send_alert, give_role, etc. |
| `effect_config` | Text | NOT NULL, default "{}" | JSON: duration_minutes, custom_message, delete_days, etc. |
| `conditions` | Text | NOT NULL, default "{}" | JSON: per-rule condition overrides |

## WordList

**Table:** `word_lists`  — **File:** `database/models/ruleset.py`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `guild_id` | String(32) | FK → guilds.discord_id, NOT NULL, indexed | |
| `name` | String(64) | NOT NULL | |
| `list_type` | String(16) | NOT NULL, default "word" | "word" or "domain" |
| `entries` | Text | NOT NULL, default "[]" | JSON array of strings |
| `created_at` | DateTime | NOT NULL, default utcnow | |

## VoiceSession

**Table:** `voice_sessions`  — **File:** `database/models/voice.py`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `guild_id` | String(32) | FK → guilds.discord_id, NOT NULL | |
| `user_id` | String(32) | NOT NULL, indexed | |
| `user_tag` | String(64) | NOT NULL, default "Unknown#0000" | |
| `channel_id` | String(32) | NOT NULL | |
| `channel_name` | String(128) | NOT NULL, default "Unknown" | |
| `joined_at` | DateTime | NOT NULL, default utcnow | |
| `left_at` | DateTime | NULL | NULL = still connected |
| `duration_seconds` | BigInteger | NULL | Computed on leave |

## FileAttachment

**Table:** `file_attachments`  — **File:** `database/models/attachments.py`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `guild_id` | String(32) | FK → guilds.discord_id, NOT NULL | |
| `channel_id` | String(32) | NOT NULL | |
| `message_id` | String(32) | NOT NULL | |
| `author_id` | String(32) | NOT NULL | |
| `author_tag` | String(64) | NOT NULL, default "Unknown#0000" | |
| `filename` | String(512) | NOT NULL | |
| `file_url` | Text | NOT NULL | |
| `file_size` | BigInteger | NOT NULL, default 0 | Bytes |
| `content_type` | String(128) | NOT NULL, default "application/octet-stream" | MIME type |
| `is_image` | Boolean | default False | |
| `created_at` | DateTime | NOT NULL, default utcnow | |

## ActivitySnapshot

**Table:** `activity_snapshots`  — **File:** `database/models/analytics.py`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `guild_id` | String(32) | FK → guilds.discord_id, NOT NULL, indexed | |
| `snapshot_date` | Date | NOT NULL | Date of snapshot |
| `total_messages` | Integer | NOT NULL, default 0 | |
| `total_voice_minutes` | Integer | NOT NULL, default 0 | |
| `total_reactions` | Integer | NOT NULL, default 0 | |
| `active_members` | Integer | NOT NULL, default 0 | |
| `new_members` | Integer | NOT NULL, default 0 | |
| `left_members` | Integer | NOT NULL, default 0 | |
| `total_members` | Integer | NOT NULL, default 0 | |
| `mod_cases` | Integer | NOT NULL, default 0 | |
| `automod_triggers` | Integer | NOT NULL, default 0 | |
| `message_authors` | Integer | NOT NULL, default 0 | |
| `channels_active` | Integer | NOT NULL, default 0 | |
| `total_channels` | Integer | NOT NULL, default 0 | |
| `threads_created` | Integer | NOT NULL, default 0 | |
| `created_at` | DateTime | NOT NULL, default utcnow | |

## DashboardUser

**Table:** `dashboard_users`  — **File:** `database/models/permissions.py`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `discord_id` | String(32) | UNIQUE, NOT NULL, indexed | Discord user snowflake |
| `username` | String(64) | NOT NULL | |
| `avatar_url` | String(512) | NOT NULL, default "" | |
| `role` | String(16) | NOT NULL, default "viewer" | viewer, moderator, admin, owner |
| `last_login` | DateTime | NULL | |

## DashboardGuildAccess

**Table:** `dashboard_guild_access`  — **File:** `database/models/permissions.py`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `user_discord_id` | String(32) | FK → dashboard_users.discord_id, CASCADE, indexed | |
| `guild_id` | String(32) | NOT NULL, indexed | |
| `name` | String(100) | NOT NULL | Guild name at OAuth sync time |
| `icon_hash` | String(128) | NULL | |
| `permissions` | Integer | NOT NULL, default 0 | Discord permission bitmask |
| `owner` | Boolean | NOT NULL, default False | Is guild owner |
| `can_manage` | Boolean | NOT NULL, default False | Has MANAGE_GUILD permission |
| `roles` | String(512) | NOT NULL, default "" | Comma-separated Discord role IDs snapshotted at OAuth login (migration 0009; used by the per-server "Ready to manage" check) |

**Constraints:** UNIQUE(user_discord_id, guild_id) — enforced by the model on fresh databases and by migration 0010 (`uq_dashboard_user_guild` unique index, added after deduping legacy rows) on existing ones

## ModuleRoleAccess

**Table:** `module_role_access`  — **File:** `database/models/permissions.py`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `guild_id` | String(32) | FK → guilds.discord_id, NOT NULL, indexed | |
| `module_name` | String(64) | NOT NULL | |
| `min_role` | String(16) | NOT NULL, default "admin" | viewer, moderator, admin, owner |

**Constraints:** UNIQUE(guild_id, module_name)
