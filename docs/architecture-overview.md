# Architecture Overview

## Product Purpose

Bark is a self-hosted Discord server management platform. It combines a Discord bot (discord.py) with a FastAPI web dashboard (Jinja2 templates, glassmorphism CSS) to provide guild moderators and administrators with a browser-based alternative to Discord's native moderation tools. The system is modular — each feature set (moderation, logging, welcome) is a pluggable `BarkModule`.

## Folder Structure

```
bark/
├── bot/
│   ├── client.py              # BarkBot — main discord.py Client subclass
│   └── ...
├── config/
│   ├── __init__.py             # Singleton config object
│   └── ...
├── database/
│   ├── engine.py               # SQLAlchemy async engine + session_scope
│   └── models/
│       ├── guild.py            # Guild, GuildSetting
│       ├── module.py           # ModuleConfig
│       ├── moderation.py       # ModerationCase, Warning, UserNote, AuditLog
│       ├── permissions.py      # DashboardUser, DashboardGuildAccess, ModuleRoleAccess
│       ├── logging.py          # LogConfig
│       ├── automod.py          # AutoModConfig
│       ├── ruleset.py          # RuleSet, Rule, WordList
│       ├── voice.py            # VoiceSession
│       ├── analytics.py        # ActivitySnapshot
│       └── attachments.py      # FileAttachment
├── modules/
│   ├── base.py                 # BarkModule ABC + dataclasses
│   ├── moderation/module.py    # ModerationModule (v4.0.0)
│   ├── logging/module.py       # LoggingModule (v3.0.0)
│   └── welcome/module.py       # WelcomeModule (v1.0.0)
├── services/
│   ├── module_manager.py       # ModuleManager — lifecycle, discovery
│   ├── event_bus.py            # EventBus — pub/sub for Discord events
│   ├── bark_context.py         # BarkContext — module-facing gateway
│   ├── moderation_service.py   # ModerationService — business logic
│   ├── permission_service.py   # PermissionService — RBAC
│   ├── response.py             # API response helpers + check_api_permission
│   ├── security.py             # AuthMiddleware, SecurityMiddleware, rate limiting
│   ├── realtime_bridge.py      # RealtimeBridge — SSE event streaming
│   └── dashboard_access.py     # OAuth guild access helpers
├── dashboard/
│   ├── __init__.py             # create_app() — FastAPI app factory
│   ├── routes/
│   │   ├── api/                # REST API routers (see api-contracts.md)
│   │   └── web/                # Jinja2 page routes
│   ├── templates/
│   │   ├── base.html           # Shell: sidebar, context-bar, dialog
│   │   ├── pages/              # Page-level templates
│   │   │   ├── dashboard.html  # Guild selection
│   │   │   ├── guild.html      # Guild overview — stats, activity, quick actions
│   │   │   ├── modules.html    # All modules grid
│   │   │   ├── module_detail.html  # Module workspace (Operate/Configure/About + extra tabs)
│   │   │   ├── moderation.html # Moderation-specific page
│   │   │   ├── members.html    # Member directory
│   │   │   ├── member_detail.html # Member detail view
│   │   │   └── settings.html   # Guild settings page
│   │   └── module_tabs/        # Extra tab partials per module
│   │       ├── moderation_notes.html
│   │       ├── moderation_warnings.html
│   │       ├── moderation_cases.html
│   │       ├── moderation_rulesets.html
│   │       ├── moderation_wordlists.html
│   │       └── moderation_voice.html
│   └── static/
│       ├── css/main.css        # All dashboard styles and responsive rules
│       └── js/
│           ├── main.js         # Global UX: palette, dialog, navigation, tabs
│           ├── module-workspace.js # Generic module workspace controller
│           └── moderation-workspace.js # Moderation-specific tab CRUD
├── tests/
│   ├── conftest.py             # DB fixture + env setup
│   ├── test_dashboard/
│   │   ├── test_api.py         # API endpoint tests (httpx)
│   │   └── test_frontend_a11y_contract.py  # AST-based template/CSS contract tests
│   └── test_services/
│       └── test_realtime_bridge.py  # EventBus → RealtimeBridge integration
└── docs/
    ├── architecture-overview.md   # (this file)
    ├── api-contracts.md
    ├── data-model.md
    ├── permissions-model.md
    ├── testing.md
    ├── design-system.md
    ├── module-workspace.md
    ├── moderation-tab-architecture.md
    ├── moderation-workflows.md
    ├── dashboard.md
    └── coverage-map.md
```

## Module System Lifecycle

Every feature is a `BarkModule` subclass (`modules/base.py`). The `ModuleManager` (`services/module_manager.py`) discovers, loads, enables/disables, and manages all modules.

| Phase | Method | What happens |
|---|---|---|
| **Discovery** | `ModuleManager.discover()` | Scans `modules/` packages via `pkgutil.iter_modules`, finds `BarkModule` subclasses, instantiates them. |
| **Registration** | `_register_module()` | Stores instance in `self._modules[name]` and page registrations. |
| **Enable** | `ModuleManager.enable_module(name)` | Calls `module.enable()`, registers slash commands with `bot.tree`, subscribes EventBus handlers with `_guard_event_handler`. |
| **Disable** | `ModuleManager.disable_module(name)` | Calls `module.disable()`, removes commands from `bot.tree`, unsubscribes EventBus handlers. |
| **Reload** | `ModuleManager.reload_module(name)` | Disables, re-imports the package (`importlib.reload`), registers replacement, re-enables. |

Modules declare their capabilities through these abstract methods on `BarkModule` (`modules/base.py`):

| Method | Returns | Purpose |
|---|---|---|
| `get_commands()` | `list[CommandRegistration]` | Slash commands the module provides |
| `get_events()` | `list[EventRegistration]` | Discord events the module listens to |
| `get_dashboard_pages()` | `list[PageRegistration]` | Dashboard sidebar pages the module contributes |
| `get_settings_schema()` | `dict` | JSON Schema for the module's config form |
| `get_permissions()` | `list[PermissionDefinition]` | Granular permissions this module defines |
| `get_api_routes()` | `APIRouter \| None` | Module-specific API routes |
| `get_actions()` | `list[dict]` | Dashboard-doable operations (forms shown in Operate tab) |
| `get_extra_tabs()` | `list[dict]` | Extra tab partials rendered in the module workspace |
| `get_about()` | `list[dict]` | About-section stories for the dashboard |

## Startup Flow

1. **`bot/client.py`**: `BarkBot` (discord.py `commands.Bot` subclass) initializes, creates `ModuleManager`
2. **`ModuleManager.discover()`**: Scans `modules/` for BarkModule subclasses
3. **`ModuleManager.register_api_routes(app)`**: Mounts module API routers under `/api/v1`
4. **`dashboard/__init__.py` `create_app(bot)`**: Creates FastAPI app, attaches middleware (AuthMiddleware → SessionMiddleware → SecurityMiddleware → TrustedHostMiddleware), mounts static files, registers all web + API + auth routers
5. **`RealtimeBridge`**: Subscribes to EventBus, starts SSE streaming
6. **`load_module_role_access_cache()`**: Loads all ModuleRoleAccess overrides into the sync cache
7. **Modules enable** on first guild join / config load

## Event Flow

```
Discord Gateway
    ↓ (raw event)
BarkBot.on_* methods
    ↓
EventBus.emit(event_name, **data)
    ↓
ModuleManager._guard_event_handler (checks per-guild enabled)
    ↓
Module handler (e.g. ModerationModule._on_message)
    ↓
BarkContext (service facade)
    ↓
ModerationService / other services (SQLAlchemy CRUD)
    ↓
RealtimeBridge listens to EventBus → SSE to dashboard clients
```

The `EventBus` (`services/event_bus.py`) is a simple pub/sub — modules subscribe to event names via `ModuleManager.enable_module()`. The `_guard_event_handler` wrapper silently drops events for guilds where the module is disabled.

## Dashboard Navigation Structure

The manifest API (`dashboard/routes/api/manifest.py`) returns a structured navigation tree:

```
Core Pages (no category)
├── /guild/{id}              # Dashboard — overview, stats, activity feed
├── /guild/{id}/members      # Members — directory, search, filters
├── /guild/{id}/modules      # Modules — grid of every installed module
└── /guild/{id}/settings     # General Settings

Module Pages (per-module from PageRegistration)
├── Cases (moderation tab)
├── Warnings (moderation tab)
├── Notes (moderation tab)
├── Rulesets (moderation tab)
├── Word Lists (moderation tab)
└── Voice (moderation tab)

Settings Pages
└── General (core)
```

Categories: `_core` (priority -1), `community` (priority 2), `_modules` (priority 3), `settings` (priority 4).

## Key Architectural Decisions

| Decision | Rationale |
|---|---|
| **FastAPI + Jinja2 (not SPA)** | Server-rendered HTML avoids client-side bundle complexity. JS enhances only (event delegation, no framework). |
| **Modular plugin system** | Each feature is a `BarkModule` subclass. Enables independent development, testing, and per-guild toggling. |
| **Service layer** | `ModerationService` (and future module services) contains all business logic. API routes and slash commands both delegate to services. |
| **EventBus for decoupling** | Modules never call each other directly. They emit and subscribe to events through `EventBus`. |
| **SSE for real-time** | Server-Sent Events over WebSockets — simpler infrastructure, unidirectional server→client stream, works through standard proxies. |
| **Permission cache** | `ModuleRoleAccess` overrides are loaded into a sync dict at startup so auth middleware can check permissions without awaiting DB. |
| **SQLite by default** | Single-file deployment. SQLAlchemy async engine makes swapping to Postgres straightforward. |
| **SessionMiddleware + OAuth2** | Discord OAuth2 flow authenticates dashboard users; `SessionMiddleware` persists the user. Role-based access control (`viewer`/`moderator`/`admin`/`owner`) gates every mutation. |
| **CSP + rate limiting** | Strict Content-Security-Policy headers, bounded per-identity request-window limiting (authenticated user ID, otherwise client IP; 3× cap for GET, ½ cap for writes), and CORS origin enforcement all live in `SecurityMiddleware`. |
