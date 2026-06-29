# Bark Architecture

## Overview

Bark is a server management platform for the ZENHAWX Discord community. The dashboard is the primary interface; the Discord bot is the execution layer.

## System Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Dashboard                         │
│  (FastAPI + Jinja2 + SQLAlchemy + SQLite)           │
│                                                      │
│  ┌─────────┐ ┌──────────┐ ┌──────────────────────┐  │
│  │  Web UI │ │ REST API │ │  Template Engine      │  │
│  │  (Svelte│ │ /api/v1/ │ │  (Jinja2 + HTMX)      │  │
│  │  + CSS) │ │          │ │                       │  │
│  └────┬────┘ └────┬─────┘ └──────────────────────┘  │
│       │           │                                  │
│  ┌────▼───────────▼──────────────────────────────┐   │
│  │              Services Layer                    │   │
│  │  ┌────────────┐ ┌──────────┐ ┌──────────┐    │   │
│  │  │ ModuleMgr  │ │ PermsSvc │ │ AuditSvc │    │   │
│  │  └────────────┘ └──────────┘ └──────────┘    │   │
│  └───────────────────────────────────────────────┘   │
│                        │                              │
│  ┌────────────────────▼───────────────────────────┐  │
│  │              Database Layer                     │  │
│  │  (SQLAlchemy ORM → SQLite)                     │  │
│  └────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
                        │
                        │ IPC (shared DB / HTTP)
                        │
┌───────────────────────▼────────────────────────────┐
│                  Discord Bot                         │
│  (discord.py client + event handlers)               │
│                                                      │
│  ┌────────────┐ ┌──────────┐ ┌──────────────────┐  │
│  │  Commands  │ │  Events  │ │  Module Runner   │  │
│  │  (Slash +  │ │  (on_*)  │ │  (enabled mods   │  │
│  │   Prefix)  │ │          │ │   active here)   │  │
│  └────────────┘ └──────────┘ └──────────────────┘  │
└──────────────────────────────────────────────────────┘
```

## Module System

All functionality is implemented as modules. Each module registers:

- Discord commands (slash + prefix)
- Event listeners
- Dashboard pages
- API routes
- Permission requirements
- Configuration schema

### Module Lifecycle

```
Discovery → Registration → Enable → Runtime → Disable → Reload
              └── Configure ──┘
```

1. **Discovery**: ModuleManager scans modules/ directory for BarkModule subclasses
2. **Registration**: Module registers its capabilities (commands, events, pages)
3. **Enable**: Module hooks into bot events, registers commands, loads config
4. **Configure**: Settings loaded from database, applied to runtime behavior
5. **Runtime**: Module processes events/commands
6. **Disable**: Module unhooks events, removes commands, cleans up
7. **Reload**: Disable + re-Enable with fresh config

### Base Module Interface

```python
class BarkModule:
    name: str          # Unique module identifier
    version: str       # Semver
    description: str   # Human-readable description
    author: str        # Module author

    async def enable(self) -> None
    async def disable(self) -> None
    async def reload(self) -> None

    def get_settings_schema(self) -> dict
    def get_dashboard_pages(self) -> list[PageRegistration]
    def get_commands(self) -> list[CommandRegistration]
    def get_events(self) -> list[EventRegistration]
    def get_permissions(self) -> list[PermissionDefinition]
```

## Database Schema

### guilds
Column       | Type    | Notes
-------------|---------|-----------------------
id           | Integer | PK auto
discord_id   | String  | UNIQUE, guild snowflake
name         | String  | Guild name
owner_id     | String  | Owner snowflake
prefix       | String  | Custom command prefix
locale       | String  | Guild locale
created_at   | DateTime| Guild join time
updated_at   | DateTime| Last config change

### guild_settings
Column   | Type    | Notes
---------|---------|-------------------
id       | Integer | PK auto
guild_id | Integer | FK → guilds.id
key      | String  | Setting key
value    | Text    | JSON-encoded value
UNIQUE   |         | (guild_id, key)

### module_configs
Column      | Type    | Notes
------------|---------|-----------------------
id          | Integer | PK auto
guild_id    | Integer | FK → guilds.id
module_name | String  | Module identifier
enabled     | Boolean | Is module active
priority    | Integer | Load order priority
config      | Text    | JSON-encoded config JSON
UNIQUE      |         | (guild_id, module_name)

### moderation_cases
Column        | Type    | Notes
--------------|---------|-----------------------
id            | Integer | PK auto
guild_id      | Integer | FK → guilds.id
case_number   | Integer | Per-guild incrementing
action_type   | String  | warn/timeout/kick/ban/unban
target_id     | String  | Target user snowflake
target_tag    | String  | Target username#discrim
moderator_id  | String  | Moderator snowflake
moderator_tag | String  | Moderator tag
reason        | Text    | Reason for action
duration      | Integer | Timeout duration (minutes)
created_at    | DateTime| When action was taken
resolved      | Boolean | Is case resolved
resolved_at   | DateTime| When resolved
UNIQUE        |         | (guild_id, case_number)

### warnings
Column      | Type    | Notes
------------|---------|-----------------------
id          | Integer | PK auto
guild_id    | Integer | FK → guilds.id
case_id     | Integer | FK → moderation_cases.id
user_id     | String  | Warned user snowflake
moderator_id| String  | Moderator snowflake
reason      | Text    | Warning reason
created_at  | DateTime| When warned
active      | Boolean | Is warning still active

### log_configs
Column      | Type    | Notes
------------|---------|-----------------------
id          | Integer | PK auto
guild_id    | Integer | FK → guilds.id
event_type  | String  | Event type identifier
channel_id  | String  | Target channel snowflake
enabled     | Boolean | Is logging enabled
UNIQUE      |         | (guild_id, event_type)

### automod_configs
Column          | Type    | Notes
----------------|---------|-----------------------
id              | Integer | PK auto
guild_id        | Integer | FK → guilds.id
rule_type       | String  | spam/invite/mention
enabled         | Boolean | Is rule active
threshold       | Integer | Trigger threshold
action          | String  | warn/timeout/delete
duration        | Integer | Action duration (min)
ignored_roles   | Text    | JSON array of role IDs
ignored_channels| Text    | JSON array of channel IDs
UNIQUE          |         | (guild_id, rule_type)

### user_notes
Column      | Type    | Notes
------------|---------|-----------------------
id          | Integer | PK auto
guild_id    | Integer | FK → guilds.id
user_id     | String  | Target user snowflake
author_id   | String  | Note author snowflake
content     | Text    | Note content
created_at  | DateTime| When written

### dashboard_users
Column     | Type    | Notes
-----------|---------|-----------------------
id         | Integer | PK auto
discord_id | String  | UNIQUE, user snowflake
username   | String  | Display name
avatar_url | String  | Avatar URL
role       | String  | admin/moderator/viewer
last_login | DateTime| Last dashboard login

### audit_logs
Column      | Type    | Notes
------------|---------|-----------------------
id          | Integer | PK auto
guild_id    | Integer | FK → guilds.id
action      | String  | Action identifier
actor_id    | String  | Actor snowflake
target_id   | String  | Target snowflake (optional)
details     | Text    | JSON-encoded details
created_at  | DateTime| When action occurred

## API Structure

All routes: `/api/v1/{guild_id}/...`

### Guilds
GET    /api/v1/guilds              - List user's guilds
GET    /api/v1/guilds/{id}         - Guild details
GET    /api/v1/guilds/{id}/stats   - Guild statistics

### Modules
GET    /api/v1/guilds/{id}/modules              - List modules
GET    /api/v1/guilds/{id}/modules/{name}       - Module details
PUT    /api/v1/guilds/{id}/modules/{name}       - Update module config
POST   /api/v1/guilds/{id}/modules/{name}/toggle - Enable/disable
POST   /api/v1/guilds/{id}/modules/{name}/reload - Reload module

### Moderation
GET    /api/v1/guilds/{id}/moderation/cases       - List cases
GET    /api/v1/guilds/{id}/moderation/cases/{n}   - Case details
POST   /api/v1/guilds/{id}/moderation/cases       - Create case
GET    /api/v1/guilds/{id}/moderation/warnings    - List warnings
GET    /api/v1/guilds/{id}/moderation/warnings/{uid} - User warnings
GET    /api/v1/guilds/{id}/moderation/bans        - List bans
GET    /api/v1/guilds/{id}/moderation/notes       - List notes
POST   /api/v1/guilds/{id}/moderation/notes       - Create note

### Settings
GET    /api/v1/guilds/{id}/settings               - All settings
PUT    /api/v1/guilds/{id}/settings/logging       - Log config
PUT    /api/v1/guilds/{id}/settings/automod       - AutoMod config
PUT    /api/v1/guilds/{id}/settings/general       - General config

### Audit
GET    /api/v1/guilds/{id}/audit/logs             - Audit logs

## Dashboard Pages

Base layout: sidebar navigation (left), content area (right), dark theme.

### Home
- Server overview card (name, owner, member count, created)
- Module status overview (enabled/disabled counts)
- Recent moderation actions (last 10)
- Quick action buttons (warn user, timeout user)

### Modules
- Card grid of all modules
- Each card: name, version, description, status toggle
- Configure button → inline config editor
- Priority reorder (drag)

### Moderation
- Tabbed interface: Cases | Warnings | Bans | Notes
- Data tables with sort, filter, search
- Create case / warn user forms
- Case detail view with full timeline

### Settings
- Tabbed interface: General | Logging | AutoMod
- Form-based configuration
- Save with visual feedback

## Permission Model

Three-tier role-based access control:

| Role        | Dashboard | Discord Actions |
|-------------|-----------|-----------------|
| admin       | Full      | All             |
| moderator   | Cases, Warnings, Notes, Settings (limited) | Warn, Timeout, Kick |
| viewer      | Read-only | None            |

Dashboard role is determined by:
1. Check `dashboard_users` table for explicit role
2. Fall back to Discord role mapping in guild settings
3. Default to viewer if no mapping found

## Technology Stack

| Component      | Technology         | Rationale                          |
|----------------|--------------------|-----------------------------------|
| Bot Framework  | discord.py 2.x     | Mature, well-maintained           |
| Web Framework  | FastAPI            | Async, fast, great DX             |
| Templates      | Jinja2             | Simple, powerful, FastAPI-native  |
| ORM            | SQLAlchemy 2.x     | Battle-tested, async support      |
| Database       | SQLite             | Zero config, sufficient for scale |
| CSS            | Custom (no framework) | Lightweight, no bloat          |
| JS             | Vanilla + HTMX     | Minimal JS, htmx for interactivity|

## Deployment

Development:
```bash
python app.py                    # Runs both bot + dashboard
```

Production:
```bash
# Option A: Single process
python app.py

# Option B: Separate processes
python -m bot         # Bot process
python -m dashboard   # Dashboard process (shared DB)
```

## Extension Points

The architecture explicitly supports adding:

1. **New modules**: Drop into modules/ directory, register capabilities
2. **Custom auth providers**: OAuth2 service can be swapped
3. **Database backends**: SQLAlchemy makes Postgres/MySQL a config change
4. **Dashboard themes**: CSS variables in base template
5. **Plugin packages**: pip-installable modules (future)
6. **Webhook integrations**: Event bus for external services
7. **Analytics pipeline**: Decoupled event logging table
