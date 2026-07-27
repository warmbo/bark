# API Contracts

All routes return JSON responses from `services/response.py` helpers: `api_success(data)` → `{"success": true, "data": ...}`, `api_error(msg, code)` → `{"success": false, "error": "..."}`, `api_paginated(items, total, page, limit)` → `{"success": true, "data": {"items": [...], "total": N, "page": N, "pages": N}}`.

Base path: `/api/v1/` (or `/api/v1/guilds/{guild_id}/...` for guild-scoped endpoints).

## Health

| Method | Path | Auth | Description | Source file |
|---|---|---|---|---|
| GET | `/api/v1/health` | Public | System health — bot status, DB connection, module health, uptime, memory | `dashboard/routes/api/health.py` |

Response shape:
```json
{"success": true, "data": {"status": "healthy|degraded", "version": "0.2.0",
  "uptime": {"seconds": N, "display": "Xh Ym Zs", "started_at": "ISO8601"},
  "bot": {"connected": bool, "ready": bool, "guilds": N, "user": "str|null"},
  "database": {"healthy": bool, "status": "str"},
  "modules": {"total": N, "enabled": N, "list": {name: {"version": "str", "enabled": bool, ...}}},
  "memory": {"total_events": N}}}
```

## Guilds

| Method | Path | Auth | Description | Source file |
|---|---|---|---|---|
| GET | `/api/v1/guilds` | Session | List accessible guilds (with OAuth filters when enabled) | `dashboard/routes/api/guilds.py` |
| GET | `/api/v1/guilds/{guild_id}` | Session | Detailed guild info — name, members, channels, roles, boosts, premium | `dashboard/routes/api/guilds.py` |
| GET | `/api/v1/guilds/{guild_id}/stats` | Session | Live guild stats — online members, voice count, cases 7d, growth 30d, cases by type | `dashboard/routes/api/guilds.py` |
| GET | `/api/v1/guilds/{guild_id}/roles` | Session | All roles (id, name, color) for filtering | `dashboard/routes/api/guilds.py` |
| GET | `/api/v1/guilds/{guild_id}/channels` | Session | Sorted text channels (id, name, parent_name, type) | `dashboard/routes/api/guilds.py` |
| GET | `/api/v1/guilds/{guild_id}/activity` | Session | Aggregated feed — last 10 cases, audits, voice sessions, warnings (merged, sorted, max 25) | `dashboard/routes/api/guilds.py` |
| GET | `/api/v1/guilds/{guild_id}/manifest` | Session | Full navigation + capabilities manifest for dashboard rendering | `dashboard/routes/api/manifest.py` |

`GET /api/v1/guilds/{guild_id}/stats` response:
```json
{"members": N, "members_online": N, "channels": N, "roles": N, "boosts": N,
 "in_voice": N, "growth_30d": N, "total_cases": N, "cases_7d": N, "cases_by_type": {"warn": N, ...}}
```

## Members

| Method | Path | Auth | Description | Source file |
|---|---|---|---|---|
| GET | `/api/v1/guilds/{guild_id}/members` | Session | List/search members with filters (search, role_id, min_age_days, max_age_days), sorting (name/joined_at/account_age/role), pagination (page, limit up to 100) | `dashboard/routes/api/actions.py` |
| GET | `/api/v1/guilds/{guild_id}/members/{user_id}` | Session | Full member detail — profile, cases, warnings, notes, voice sessions | `dashboard/routes/api/actions.py` |

## Moderation Actions

| Method | Path | Auth | Description | Source file |
|---|---|---|---|---|
| POST | `/api/v1/guilds/{guild_id}/actions/warn` | moderation.warn | Warn member — DM + warning record + case | `dashboard/routes/api/actions.py` |
| POST | `/api/v1/guilds/{guild_id}/actions/timeout` | moderation.timeout | Timeout member — duration in minutes (default 10) | `dashboard/routes/api/actions.py` |
| POST | `/api/v1/guilds/{guild_id}/actions/kick` | moderation.kick | Kick member from server | `dashboard/routes/api/actions.py` |
| POST | `/api/v1/guilds/{guild_id}/actions/ban` | moderation.ban | Ban member — optional delete_message_days | `dashboard/routes/api/actions.py` |
| POST | `/api/v1/guilds/{guild_id}/actions/vc_kick` | moderation.vc_kick | Disconnect from voice | `dashboard/routes/api/actions.py` |
| POST | `/api/v1/guilds/{guild_id}/actions/vc_move` | moderation.vc_move | Move to another voice channel (channel_id in duration field) | `dashboard/routes/api/actions.py` |
| POST | `/api/v1/guilds/{guild_id}/actions/vc_mute` | moderation.vc_mute | Server-mute in voice | `dashboard/routes/api/actions.py` |
| POST | `/api/v1/guilds/{guild_id}/actions/vc_unmute` | moderation.vc_unmute | Server-unmute in voice | `dashboard/routes/api/actions.py` |
| POST | `/api/v1/guilds/{guild_id}/actions/unban` | moderation.unban | Unban user by ID | `dashboard/routes/api/actions.py` |

All action POST routes accept `{"target_id": "discord_id", "reason": "...", "duration": (minutes, optional)}`. Returns `{"case": case_number, "action": "str", "target": "str"}`.

Each action also checks:
1. Dashboard permission (`check_api_permission`)
2. Bot's Discord guild permission (`_ACTION_PERMISSIONS` map)
3. Actor's Discord guild permission and role hierarchy (kick/ban/timeout require actor's top role > target's top role)

## Moderation Data

| Method | Path | Auth | Description | Source file |
|---|---|---|---|---|
| GET | `/api/v1/guilds/{guild_id}/moderation/cases` | Session | Paginated unresolved cases (page, limit) | `dashboard/routes/api/moderation.py` |
| GET | `/api/v1/guilds/{guild_id}/moderation/cases/{case_number}` | Session | Single case detail | `dashboard/routes/api/moderation.py` |
| POST | `/api/v1/guilds/{guild_id}/moderation/cases` | moderation.cases.create | Create case directly | `dashboard/routes/api/moderation.py` |
| DELETE | `/api/v1/guilds/{guild_id}/moderation/cases/{case_number}` | moderation.cases.delete | Soft-delete (marks resolved) | `dashboard/routes/api/moderation.py` |
| GET | `/api/v1/guilds/{guild_id}/moderation/warnings` | Session | List all active warnings | `dashboard/routes/api/moderation.py` |
| GET | `/api/v1/guilds/{guild_id}/moderation/warnings/{user_id}` | Session | List warnings for a user | `dashboard/routes/api/moderation.py` |
| DELETE | `/api/v1/guilds/{guild_id}/moderation/warnings/{warning_id}` | moderation.warnings.delete | Deactivate a warning | `dashboard/routes/api/moderation.py` |
| GET | `/api/v1/guilds/{guild_id}/moderation/voice-history` | Session | Recent voice sessions (limit, enriched with resolved names) | `dashboard/routes/api/moderation.py` |
| DELETE | `/api/v1/guilds/{guild_id}/moderation/voice-history` | guild.manage | Purge all voice session records | `dashboard/routes/api/moderation.py` |
| DELETE | `/api/v1/guilds/{guild_id}/moderation/audit-logs` | guild.manage | Purge all audit logs | `dashboard/routes/api/moderation.py` |
| DELETE | `/api/v1/guilds/{guild_id}/moderation/attachments` | guild.manage | Purge all file attachment records | `dashboard/routes/api/moderation.py` |

## Notes

| Method | Path | Auth | Description | Source file |
|---|---|---|---|---|
| GET | `/api/v1/guilds/{guild_id}/notes` | Session | List all notes (last 100, most recent first) | `dashboard/routes/api/notes.py` |
| GET | `/api/v1/guilds/{guild_id}/notes/user/{user_id}` | Session | List notes for a specific user | `dashboard/routes/api/notes.py` |
| POST | `/api/v1/guilds/{guild_id}/notes` | moderation.notes.create | Create note (`{"user_id": "...", "content": "..."}`) | `dashboard/routes/api/notes.py` |
| PATCH | `/api/v1/guilds/{guild_id}/notes/{note_id}` | moderation.notes.create | Update note content (max 2000 chars) | `dashboard/routes/api/notes.py` |
| DELETE | `/api/v1/guilds/{guild_id}/notes/{note_id}` | moderation.notes.create | Delete note | `dashboard/routes/api/notes.py` |

## Modules

| Method | Path | Auth | Description | Source file |
|---|---|---|---|---|
| GET | `/api/v1/guilds/{guild_id}/modules` | Session | List all modules with config, status, schema | `dashboard/routes/api/modules.py` |
| GET | `/api/v1/guilds/{guild_id}/modules/{module_name}` | module.access | Get module details | `dashboard/routes/api/modules.py` |
| PUT | `/api/v1/guilds/{guild_id}/modules/{module_name}` | module.configure | Update module config (validated against schema) | `dashboard/routes/api/modules.py` |
| POST | `/api/v1/guilds/{guild_id}/modules/{module_name}/toggle` | module.manage | Enable/disable module | `dashboard/routes/api/modules.py` |
| POST | `/api/v1/guilds/{guild_id}/modules/{module_name}/reload` | module.manage | Hot-reload module code | `dashboard/routes/api/modules.py` |
| POST | `/api/v1/guilds/{guild_id}/modules/{module_name}/test` | module.configure | Execute module test action (logging: sends test message) | `dashboard/routes/api/modules.py` |
| GET | `/api/v1/guilds/{guild_id}/modules/role-access` | modules.manage | Get all module role overrides | `dashboard/routes/api/modules.py` |
| PATCH | `/api/v1/guilds/{guild_id}/modules/{module_name}/role-access` | modules.manage | Set module min role (`{"min_role": "viewer|moderator|admin|owner"}`) | `dashboard/routes/api/modules.py` |
| DELETE | `/api/v1/guilds/{guild_id}/modules/{module_name}/role-access` | modules.manage | Remove override (restores admin default) | `dashboard/routes/api/modules.py` |

## Settings

| Method | Path | Auth | Description | Source file |
|---|---|---|---|---|
| GET | `/api/v1/guilds/{guild_id}/settings` | Session | All GuildSetting key/value pairs | `dashboard/routes/api/settings.py` |
| GET | `/api/v1/guilds/{guild_id}/settings/health` | Session | Validate all module configs against their schemas | `dashboard/routes/api/settings.py` |
| PUT | `/api/v1/guilds/{guild_id}/settings/general` | settings.general | Update general settings (upsert GuildSetting rows) | `dashboard/routes/api/settings.py` |
| GET | `/api/v1/guilds/{guild_id}/settings/logging` | Session | Logging config (event_type → channel_id + enabled) | `dashboard/routes/api/settings.py` |
| PUT | `/api/v1/guilds/{guild_id}/settings/logging` | logging.configure | Update logging config | `dashboard/routes/api/settings.py` |
| GET | `/api/v1/guilds/{guild_id}/settings/automod` | Session | AutoMod config (per-rule-type) | `dashboard/routes/api/settings.py` |
| PUT | `/api/v1/guilds/{guild_id}/settings/automod` | settings.automod | Update AutoMod config | `dashboard/routes/api/settings.py` |

## Audit Log

| Method | Path | Auth | Description | Source file |
|---|---|---|---|---|
| GET | `/api/v1/guilds/{guild_id}/audit-log` | Session | Discord audit log entries (limit, optional category filter) | `dashboard/routes/api/audit_log.py` |
| GET | `/api/v1/guilds/{guild_id}/audit-log/summary` | Session | Summary counts (last hour, 24h, total, by_action) | `dashboard/routes/api/audit_log.py` |

## Real-time

| Method | Path | Auth | Description | Source file |
|---|---|---|---|---|
| GET | `/api/v1/guilds/{guild_id}/events` | Session | SSE stream — pushes `new_moderation_case`, `member_joined`, `automod_triggered` events. Heartbeat every 30s, disconnect after 60s idle. | `dashboard/routes/api/realtime.py` |

## Auth

| Method | Path | Auth | Description | Source file |
|---|---|---|---|---|
| GET | `/auth/login` | Public | Discord OAuth2 login redirect | `dashboard/routes/auth.py` |
| GET | `/auth/callback` | Public | OAuth2 callback — exchanges code, creates/updates DashboardUser, sets session | `dashboard/routes/auth.py` |
| GET | `/auth/logout` | Session | Clear session + redirect to login | `dashboard/routes/auth.py` |
| GET | `/auth/me` | Public | Return current user from session (or null) | `dashboard/routes/auth.py` |

## Web (HTML) Routes

| Method | Path | Source file |
|---|---|---|
| GET | `/` → redirect to `/dashboard` | `dashboard/__init__.py` |
| GET | `/dashboard` | `dashboard/__init__.py` |
| GET | `/guild/{guild_id}` | `dashboard/routes/web/home.py` |
| GET | `/guild/{guild_id}/modules` | `dashboard/routes/web/modules.py` |
| GET | `/guild/{guild_id}/modules/{module_name}` | `dashboard/routes/web/modules.py` |
| GET | `/guild/{guild_id}/members` | `dashboard/routes/web/members.py` |
| GET | `/guild/{guild_id}/members/{user_id}` | `dashboard/routes/web/members.py` |
| GET | `/guild/{guild_id}/moderation` | `dashboard/routes/web/moderation.py` |
| GET | `/guild/{guild_id}/settings` | `dashboard/routes/web/settings.py` |

## API Response Helpers

Defined in `services/response.py`:

| Helper | HTTP Status | Response Shape |
|---|---|---|
| `api_success(data)` | 200 | `{"success": true, "data": ...}` |
| `api_created(data)` | 201 | `{"success": true, "data": ...}` |
| `api_deleted()` | 200 | `{"success": true, "data": {"deleted": true}}` |
| `api_error(msg, status)` | 400 (default) | `{"success": false, "error": "..."}` |
| `api_not_found(resource)` | 404 | `{"success": false, "error": "Resource not found"}` |
| `api_forbidden(msg)` | 403 | `{"success": false, "error": "..."}` |
| `api_paginated(items, total, page, limit)` | 200 | `{"success": true, "data": {"items": [...], "total": N, "page": N, "pages": N}}` |
