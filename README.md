# Bark

A dashboard-first Discord server management platform for the ZENHAWX community.

**Dashboard is the primary interface. The Discord bot is the execution layer.**

## Architecture

```
bark/                          # Project root
├── app.py                     # Main entry point (bot + dashboard)
├── config.py                  # Environment-based configuration
├── bot/
│   └── client.py              # BarkBot (discord.ext.commands.Bot subclass)
├── dashboard/
│   ├── __init__.py            # FastAPI app factory
│   ├── app.py                 # Uvicorn server runner
│   ├── routes/api/            # REST API endpoint handlers
│   ├── routes/web/            # HTML page route handlers
│   ├── static/css/            # Stylesheets
│   ├── static/js/             # Client-side JavaScript
│   └── templates/             # Jinja2 page templates
├── database/
│   ├── engine.py              # SQLAlchemy async engine + session management
│   └── models/                # ORM models (10+ tables)
├── modules/
│   ├── base.py                # BarkModule abstract base class
│   ├── moderation/            # Warn, timeout, kick, ban, voice control
│   ├── logging/               # Message, file, member, voice event logging
│   └── automod/               # Spam, invite, mention spam detection
├── services/
│   ├── module_manager.py      # Module discovery + lifecycle management
│   └── permission_service.py  # Role-based access control
├── tests/                     # Pytest test suite
└── docs/
    └── architecture.md        # Detailed architecture document
```

### Core Philosophy

- **Dashboard-first** — manage everything from the web UI, not through Discord commands
- **Modular by design** — all features are swappable modules
- **Minimal dependencies** — Python 3.13+, discord.py, FastAPI, Jinja2, SQLAlchemy, SQLite
- **Production-ready** — async from top to bottom, proper error handling, audit logging

## Quick Start

```bash
# Set up
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Configure
export BARK_BOT_TOKEN="your_discord_bot_token"
export BARK_DASHBOARD_HOST="0.0.0.0"  # Listen on all interfaces

# Run
python app.py
```

Dashboard: `http://<host>:8090/dashboard`
Bot: Connects to Discord automatically

### Configuration

All config via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `BARK_BOT_TOKEN` | `""` | Discord bot token (required) |
| `BARK_COMMAND_PREFIX` | `!` | Prefix for text commands |
| `BARK_SYNC_COMMANDS` | `true` | Auto-sync slash commands on startup |
| `BARK_DASHBOARD_HOST` | `127.0.0.1` | Dashboard bind address |
| `BARK_DASHBOARD_PORT` | `8090` | Dashboard port |
| `BARK_SECRET_KEY` | auto | Session encryption key |
| `BARK_DATABASE_URL` | `sqlite+aiosqlite:///bark.db` | Database connection string |
| `BARK_LOG_LEVEL` | `INFO` | Logging level |
| `BARK_DATA_DIR` | `data/` | Runtime data directory |

## Dashboard Pages

| Page | URL | Description |
|------|-----|-------------|
| Server Selection | `/dashboard` | Pick a server to manage |
| Guild Overview | `/guild/{id}` | Stats, module status, recent actions |
| Members | `/guild/{id}/members` | Browse, search, moderate members |
| Member Detail | `/guild/{id}/members/{uid}` | Full profile, cases, actions, notes |
| Modules | `/guild/{id}/modules` | Module list with toggles |
| Module Detail | `/guild/{id}/modules/{name}` | Config, commands, events, reload |
| Moderation | `/guild/{id}/moderation` | Cases, warnings, bans, notes |
| Settings | `/guild/{id}/settings` | General, logging, AutoMod config |

## API Endpoints

All at `/api/v1/`.

### Guilds
- `GET /guilds` — List guilds
- `GET /guilds/{id}` — Guild details
- `GET /guilds/{id}/stats` — Guild statistics

### Members
- `GET /guilds/{id}/members` — List/search members (query: `search`, `page`, `limit`)
- `GET /guilds/{id}/members/{uid}` — Member detail with cases, warnings, notes, voice sessions

### Moderation Actions (dashboard GUI)
- `POST /guilds/{id}/actions/warn` — Warn a member
- `POST /guilds/{id}/actions/timeout` — Timeout a member
- `POST /guilds/{id}/actions/kick` — Kick a member
- `POST /guilds/{id}/actions/ban` — Ban a member
- `POST /guilds/{id}/actions/vc_kick` — Voice-disconnect a member
- `POST /guilds/{id}/actions/vc_move` — Move member to another VC
- `POST /guilds/{id}/actions/vc_mute` — Server-mute in voice
- `POST /guilds/{id}/actions/vc_unmute` — Server-unmute in voice

### Moderation Data
- `GET /guilds/{id}/moderation/cases` — List cases
- `GET /guilds/{id}/moderation/cases/{n}` — Single case
- `POST /guilds/{id}/moderation/cases` — Create case
- `GET /guilds/{id}/moderation/warnings` — List warnings
- `GET /guilds/{id}/moderation/warnings/{uid}` — User's warnings
- `GET /guilds/{id}/moderation/notes` — List notes
- `POST /guilds/{id}/moderation/notes` — Create note

### Modules
- `GET /guilds/{id}/modules` — List modules with status
- `GET /guilds/{id}/modules/{name}` — Module detail
- `PUT /guilds/{id}/modules/{name}` — Update config
- `POST /guilds/{id}/modules/{name}/toggle` — Enable/disable
- `POST /guilds/{id}/modules/{name}/reload` — Hot-reload

### Settings
- `GET /guilds/{id}/settings` — All settings
- `PUT /guilds/{id}/settings/general` — General settings
- `GET|PUT /guilds/{id}/settings/logging` — Log channel config
- `GET|PUT /guilds/{id}/settings/automod` — AutoMod rules

---

# Module Development Guide

Every Bark feature is a module. Modules are self-contained packages under `modules/` that define their own commands, events, config, and dashboard pages.

## Creating a New Module

### 1. Create the package structure

```
modules/my_module/
├── __init__.py          # Empty or re-export
└── module.py            # BarkModule subclass
```

### 2. Subclass `BarkModule`

```python
# modules/my_module/module.py
from modules.base import BarkModule, CommandRegistration, EventRegistration
from bot.client import BarkBot

class MyModule(BarkModule):
    name = "my_module"           # Unique identifier (used in DB, APIs)
    version = "1.0.0"           # Semantic version
    description = "What my module does"
    author = "Your Name"

    def __init__(self, bot: BarkBot) -> None:
        super().__init__(bot)
```

### 3. Implement lifecycle methods

```python
async def enable(self) -> None:
    """Called when module is enabled.
    Register slash commands, event listeners, and API routes here."""
    # Register a slash command
    if hasattr(self.bot, "tree"):
        self.bot.tree.add_command(self._make_my_command())
    
    # Register an event listener
    self.bot.add_listener(self._on_message, "on_message")

async def disable(self) -> None:
    """Called when module is disabled.
    Unregister everything registered in enable()."""
    if hasattr(self.bot, "tree"):
        self.bot.tree.remove_command("my_command")
```

### 4. Register capabilities

```python
def get_commands(self) -> list[CommandRegistration]:
    """Slash commands this module provides."""
    return [
        CommandRegistration(name="my_command", description="Does something cool"),
    ]

def get_events(self) -> list[EventRegistration]:
    """Discord events this module listens to."""
    return [
        EventRegistration(event_name="on_message"),
    ]

def get_settings_schema(self) -> dict:
    """JSON Schema for the dashboard config form.
    
    Each field supports:
    - title: Human-readable label
    - description: Help text shown below the field
    - placeholder: Example text shown inside the field
    - type: "string", "integer", "boolean", "array", or enum via "enum" list
    """
    return {
        "type": "object",
        "properties": {
            "my_setting": {
                "type": "string",
                "title": "My Setting",
                "description": "What this setting controls",
                "placeholder": "Enter a role ID like 123456789",
                "default": "default_value",
            },
        },
    }

def get_dashboard_pages(self) -> list[PageRegistration]:
    """Pages to show in the dashboard sidebar."""
    return [
        PageRegistration(
            route="/guild/{guild_id}/my_module",
            label="My Module",
            icon="settings",  # Lucide icon name
        ),
    ]

def get_permissions(self) -> list[PermissionDefinition]:
    """Granular permissions this module defines."""
    return [
        PermissionDefinition(
            name="my_module.do_thing",
            label="Do Thing",
            description="Permission to do the thing",
        ),
    ]
```

### 5. Create slash command

```python
def _make_my_command(self):
    @discord.app_commands.command(
        name="my_command",
        description="Does something cool"
    )
    @discord.app_commands.default_permissions(manage_guild=True)
    async def my_command(interaction: discord.Interaction, param: str):
        await self._cmd_handler(interaction, param)
    return my_command

async def _cmd_handler(self, interaction, param):
    await interaction.response.send_message(f"You said: {param}")
```

## Module Lifecycle

```
Discovery → __init__ → enable() → Runtime → disable()
                ↓                        ↑
          get_settings_schema()    get_settings_schema()
          get_commands()           get_commands()
          get_events()             get_events()
          get_dashboard_pages()    get_dashboard_pages()
```

- **Discovery**: ModuleManager scans `modules/` for `BarkModule` subclasses
- **enable()**: Register commands, events, API routes. Called on bot startup and when toggled on
- **Runtime**: Module processes Discord events and serves dashboard pages
- **disable()**: Unregister everything. Called on shutdown and when toggled off
- **Reload**: disable() → enable() — hot-reload without restarting the bot

## Settings Schema Reference

The `get_settings_schema()` method returns a JSON Schema dict that the dashboard
renders as a form. Supported field types:

| Type | Input | Extra Properties |
|------|-------|------------------|
| `"string"` | Text input | `placeholder`, `default` |
| `"integer"` | Number input | `minimum`, `maximum`, `default` |
| `"boolean"` | Toggle switch | `default` |
| `"array"` | Textarea (JSON) | `items.type`, `default` |
| `"string"` with `enum` | Dropdown | `enum: ["opt1", "opt2"]` |

All fields support:
- `title` — Field label
- `description` — Help text below the input
- `placeholder` — Example/intro text inside the input field

## Database Models

Each module can use the shared database via SQLAlchemy models. Add new models
in `database/models/` and import them in `database/models/__init__.py` so they
register with `Base.metadata` and get created on startup.

```python
# database/models/my_model.py
from sqlalchemy import String, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.engine import Base

class MyRecord(Base):
    __tablename__ = "my_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(Integer, ForeignKey("guilds.id"))
    # ... your fields ...
```

---

## Built-in Modules

### Moderation (v2.0.0)

Slash commands: `warn`, `timeout`, `kick`, `ban`, `unban`, `cases`, `warnings`,
`clearwarn`, `vc_kick`, `vc_move`, `vc_mute`, `vc_unmute`, `vc_deafen`,
`vc_undeafen`, `voice_sessions`

- Full case tracking with auto-incrementing case numbers per guild
- Audit logging for every action
- Voice session tracking (join/leave times persisted to DB)
- Dashboard GUI: member detail page has quick-action forms for all commands

### Logging (v2.0.0)

Event types: message edits, message deletes, file uploads, member joins/leaves,
moderation actions, voice state changes

- File attachment tracking with download URLs, sizes, content types
- `/logfiles` command to search uploaded files by member or type
- Configurable per-event log channels via settings page

### AutoMod (v1.0.0)

Rules: spam detection, invite filtering, mention spam

- Configurable thresholds per rule type
- Actions: warn, timeout, or delete
- Ignored roles and channels
- Dashboard config forms with descriptions

## Permissions

Three-tier RBAC:

| Role | Access |
|------|--------|
| **admin** | Full dashboard + all moderation actions |
| **moderator** | Cases, warnings, notes, text moderation, logging setup |
| **viewer** | Read-only dashboard |

Dashboard role is determined by `dashboard_users` table or Discord role mapping.

## Database Tables

| Table | Purpose |
|-------|---------|
| `guilds` | Server configuration |
| `guild_settings` | Key-value settings per guild |
| `module_configs` | Per-guild module enable/disable + config |
| `moderation_cases` | Moderation action records |
| `warnings` | Active warning records |
| `user_notes` | Internal notes about users |
| `audit_logs` | All moderation action audit trail |
| `file_attachments` | File upload logs with download URLs |
| `voice_sessions` | Voice channel join/leave history |
| `log_configs` | Per-event log channel configuration |
| `automod_configs` | AutoMod rule configuration |
| `dashboard_users` | Dashboard user role assignments |

## Testing

```bash
pytest                    # Run all tests
pytest -v                 # Verbose
pytest tests/ -k "model"  # Run specific test group
```

## Future Extension Points

The architecture supports these without restructuring:
- **New modules**: Drop a package into `modules/` with a `BarkModule` subclass
- **Custom auth**: Swap the session middleware for OAuth2
- **Database backends**: Change `BARK_DATABASE_URL` for Postgres/MySQL
- **Plugin packages**: pip-installable modules (planned)
- **Webhook integrations**: Event bus for external services (planned)
- **Analytics pipeline**: Decoupled from existing audit logs
