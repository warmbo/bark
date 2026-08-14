# Permissions Model

## Role Hierarchy

Defined in `services/permission_service.py`:

```python
ROLE_HIERARCHY = {
    "viewer": 0,
    "moderator": 1,
    "admin": 2,
    "owner": 3,
}
```

Higher numeric level = more access. A user's role must be **≥** the required role for an action.

## Core Action Map

`PermissionService.CORE_ACTIONS` (`services/permission_service.py`) defines the minimum role required for every built-in action:

### Dashboard Access
| Action | Required Role |
|---|---|
| `dashboard.access` | viewer |

### Guild Management
| Action | Required Role |
|---|---|
| `guild.manage` | admin |

### Settings
| Action | Required Role |
|---|---|
| `settings.general` | admin |
| `settings.automod` | admin |
| `settings.logging` | moderator |

### Module Management
| Action | Required Role |
|---|---|
| `modules.manage` | admin |
| `modules.configure` | admin |

### Moderation Actions
| Action | Required Role |
|---|---|
| `moderation.view` | module minimum role (admin when unset) |
| `moderation.warn` | moderator |
| `moderation.timeout` | moderator |
| `moderation.kick` | moderator |
| `moderation.ban` | moderator |
| `moderation.unban` | moderator |
| `moderation.vc_kick` | moderator |
| `moderation.vc_move` | moderator |
| `moderation.vc_mute` | moderator |
| `moderation.vc_unmute` | moderator |
| `moderation.cases.create` | moderator |
| `moderation.cases.delete` | admin |
| `moderation.warnings.delete` | moderator |
| `moderation.notes.create` | moderator |
| `moderation.notes.view` | moderator |
| `moderation.notes.delete` | moderator |

### Logging
| Action | Required Role |
|---|---|
| `logging.configure` | moderator |

### Roles
| Action | Required Role |
|---|---|
| `roles.manage` | admin |

### Dashboard Users
| Action | Required Role |
|---|---|
| `dashboard.users` | admin |

## Per-server dashboard access ("Ready to manage")

Beyond the global `viewer < moderator < admin < owner` hierarchy, each
server has its own "who may manage Bark here" rule, computed by
`user_ready_to_manage()` in `services/dashboard_access.py`:

A user is **Ready to manage** a server when any of:

1. they are the **guild owner** (`owner` flag on the access row), or
2. they hold Discord's **`ADMINISTRATOR`** permission on the server
   (mapped to the dashboard `admin` tier), or
3. they hold Discord's **`MANAGE_GUILD`** permission (mapped to the
   dashboard `moderator` tier), or
4. they hold the **admin role** the server owner configured in
   Settings → Dashboard Access (stored per-guild in `GuildSetting`
   key `dashboard_admin_role`, a single role ID), or
5. they hold a **moderator role** the server owner configured
   (`dashboard_moderator_roles`, a JSON array of role IDs).

Discord permissions map to dashboard tiers exactly as the global role
does (`derive_dashboard_role`): owner/`ADMINISTRATOR` → `admin`,
`MANAGE_GUILD` → `moderator`, and the configured staff roles add the
server owner's explicit admin/moderator designations. **Running the Bark
instance grants nothing per-server** — the instance owner is treated like
any other member unless they hold a real grant in that server (so you no
longer manage a server you only happen to be a plain member of).

Supporting pieces:

- **Role snapshot at login** — the OAuth callback resolves each guild's
  member role IDs from the bot's member cache and persists them in the
  access row's `roles` column (cookie sessions are too small for full
  guild state). Role changes therefore take effect at the next sign-in
  (documented, by design).
- **Settings → Dashboard Access** — the server owner picks **multiple
  moderator roles** (multi-select) and a **single admin role** from
  dropdowns (moderators stored as a JSON array; admin as a single role
  ID; legacy plain values still parse).
- **View-only experience** — a member of a connected server with no manage
  grant can still open it, but gets a **read-only status page** (`/guild/{id}`
  renders `guild_viewer.html`: dashboard/statistics + server info). The card
  shows **"View only"** and stays openable. The middleware blocks every
  management page (`/members`, `/modules`, `/moderation`, `/settings`) and
  module/management API route (redirect for web pages, 403 for API), and the
  manifest strips to a single Dashboard nav entry (`viewer: true`).
- **Middleware re-derivation** — `AuthMiddleware` recomputes the per-guild
  role on every guild request via `role_from_access_with_staff_roles()`
  (owner/`ADMINISTRATOR` → `admin`; `MANAGE_GUILD` or configured moderator
  role → `moderator`; configured admin role → `admin`; else `viewer`), so
  API gating matches what the dashboard cards advertise.
  `request.state.guild_viewer` is set for the view-only branch.

## Module Permission Registration

Modules declare granular permissions via `BarkModule.get_permissions()` (`modules/base.py`). Each permission is a `PermissionDefinition(name, label, description)`.

During module discovery, `ModuleManager.discover()` calls `PermissionService.discover_module_permissions(modules)`, which iterates every module and calls `register_module_permissions()`. Unknown module permissions default to `admin` unless they match a key in `CORE_ACTIONS`.

## Permission Check Flow

### 1. `check_api_permission()` (`services/response.py`)

This is the central permission gate. Called by:
- API route handlers directly (e.g. `if not check_api_permission(request, "moderation.warn", guild_id)`)
- `AuthMiddleware` for every API mutation (via `mutation_capability()`)
- `get_module_min_role()` is called async first to prime the sync cache

Flow:
```
check_api_permission(request, action, guild_id)
    │
    ├─ OAuth2 disabled? → return True (permissive mode)
    │
    ├─ user_role = request.session["role"]  (default: "viewer")
    │
    ├─ action was declared by a module (or has a module prefix)?
    │     → resolve the declaring module from PermissionService
    │     → lookup _module_role_cache[(guild_id, module_name)]
    │     → required = cached min_role or "admin"
    │
    ├─ no module prefix?
    │     → required = PermissionService.get_required_role_for_action(action)
    │
    └─ return user_level >= required_level
```

### 2. `get_module_min_role()` (`services/response.py`)

Async: queries `ModuleRoleAccess` table for `(guild_id, module_name)`, caches result in `_module_role_cache` for subsequent synchronous calls.

### 3. `set_cached_module_min_role()` (`services/response.py`)

Directly sets the cache — used after API writes to keep permissions consistent without waiting for the next DB read.

### 4. `load_module_role_access_cache()` (`services/response.py`)

Called at startup (`dashboard/__init__.py`). Loads all `ModuleRoleAccess` rows into the sync cache so `AuthMiddleware` can check permissions synchronously on every request.

### 5. Guild capability manifests

`get_guild_capabilities()` discovers each action's declaring module, primes every module's guild-specific role cache, and evaluates capabilities through the same `check_api_permission()` path used by route enforcement. The guild manifest therefore cannot advertise a moderator action that the configured module role would reject.

## AuthMiddleware Permission Enforcement

Defined in `services/security.py`. The `AuthMiddleware` intercepts every request:

1. **Public paths** (`/auth/*`, `/api/v1/health`, `/api/v1/ping`, `/static/*`, `/s/*`) → skip
2. **No session** → 401 JSON (API) or 302 redirect (HTML)
3. **Guild access check** → `user_can_manage_guild()` via `DashboardGuildAccess` table
4. **Mutation capability** → `mutation_capability(method, path)` resolves each API mutation to a capability string, then checks via `check_api_permission()`

The `mutation_capability()` function in `services/security.py` maps every API mutation path to a capability:

| Path Pattern | Capability |
|---|---|
| `actions/warn` | `moderation.warn` |
| `actions/kick` | `moderation.kick` |
| `moderation/cases` | `moderation.cases.create` |
| `moderation/cases/{id}` | `moderation.cases.delete` |
| `moderation/warnings/{id}` | `moderation.warnings.delete` |
| `moderation/notes` | `moderation.notes.create` |
| `settings/general` | `settings.general` |
| `settings/logging` | `logging.configure` |
| `settings/automod` | `settings.automod` |
| `modules/{name}/toggle` | `modules.manage` |
| `modules/{name}/reload` | `modules.manage` |
| `modules/{name}` | `modules.configure` |
| `modules/{name}/...` | `{name}.manage` |
| Unknown mutations | `guild.manage` (fail-closed) |

## OAuth2 Auth Flow

Defined in `dashboard/routes/auth.py`:

1. User visits `/auth/login` → Discord OAuth2 authorize URL → user approves
2. Discord redirects to `/auth/callback?code=...` → server exchanges code for token
3. Server fetches user identity + guild list from Discord API
4. Creates/updates `DashboardUser` record
5. Syncs guild access to `DashboardGuildAccess` (determines `can_manage` via MANAGE_GUILD permission) and snapshots each guild's member role IDs into the `roles` column
6. Assigns dashboard role: `owner` if guild owner, `admin` otherwise
7. Sets `session["user"]` and `session["role"]`
8. `AuthMiddleware` reads `session["role"]` on every subsequent request and **re-derives** the per-guild role on guild paths from the access row + configured moderator roles (see "Per-server dashboard access" above)

When OAuth2 is not configured (`config.oauth2.enabled = False`), all permission checks return `True` (permissive mode).

## ModuleRoleAccess Overrides

Per-guild, per-module minimum role overrides stored in `ModuleRoleAccess` (`database/models/permissions.py`):

| Column | Description |
|---|---|
| `guild_id` | Discord guild ID |
| `module_name` | e.g. "moderation", "logging" |
| `min_role` | "viewer", "moderator", "admin", or "owner" |

API endpoints to manage overrides:
- `GET /api/v1/guilds/{guild_id}/modules/role-access` (requires `modules.manage`)
- `PATCH /api/v1/guilds/{guild_id}/modules/{module_name}/role-access` (requires `modules.manage`)
- `DELETE /api/v1/guilds/{guild_id}/modules/{module_name}/role-access` (restores admin default)

When no override exists, modules require `admin` role (enforced via `_module_role_cache.get(key, "admin")`).

## SessionMiddleware

Configured in `dashboard/__init__.py`:

```python
app.add_middleware(
    SessionMiddleware,
    secret_key=config.dashboard.secret_key,
    max_age=config.dashboard.session_ttl,
    same_site="lax",
    https_only=config.dashboard.secure_cookies,
)
```

Session stores `{"user": {...}, "role": "viewer|moderator|admin|owner"}`. The `role` is set during OAuth login and used by all subsequent permission checks.

## Security Headers

`SecurityMiddleware` (`services/security.py`) applies:
- `Content-Security-Policy` (strict — only 'self', unpkg.com, fonts.googleapis, cdn.discordapp)
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: same-origin`
- `Strict-Transport-Security` (when `secure_cookies` enabled)
- Cross-origin write rejection (non-GET with mismatched Origin header)
- Bounded per-identity request-window limiting (authenticated user ID, otherwise client IP; 3× config cap for reads, ½ cap for writes, 429 on overflow)
