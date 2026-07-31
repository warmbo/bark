# Bark — Final Production Readiness Audit (2026-07-03)

## Summary

**Score: 8.0/10** — Up from 6.5/10 at first audit. All critical blockers resolved. Two remaining issues prevent "stable" readiness.

---

## What's Been Fixed (Since First Audit)

| Issue | Fix | Status |
|-------|-----|--------|
| CSP blocked all inline JS | Added `'unsafe-inline'` to script-src + style-src | ✅ |
| SecurityMiddleware was dead code (never wired to app) | Imported + registered in `dashboard/__init__.py` | ✅ |
| TaskGroup kills dashboard on bad bot token | Replaced with `gather(return_exceptions=True)` | ✅ |
| Disabling a module nukes other modules' event handlers | Handler-specific unsubscribe with `(event_type, handler)` tuples | ✅ |
| Dashboard mod actions don't check Discord perms | Added `_ACTION_PERMISSIONS` map + guild.me.guild_permissions check | ✅ |
| Voice count stat always showed "—" | Added `voice.in_voice` to intelligence/overview response | ✅ |
| ModuleConfig enabled default flipped between endpoints | Standardized to `True` (fresh install = enabled) | ✅ |
| Stale voice sessions leaked on restart | Cleanup task in `on_ready()` nullifies open sessions | ✅ |
| OAuth2 never persisted users | Auth callback creates/updates `DashboardUser` records; first user = owner | ✅ |
| Web routes had no auth protection | `AuthMiddleware` redirects unauthenticated to `/auth/login` | ✅ |
| `/me` returned raw dict instead of `api_success` | Fixed | ✅ |
| Skeleton loaders were static (no animation) | Added missing `@keyframes shimmer` | ✅ |
| No `prefers-reduced-motion` support | Added `@media (prefers-reduced-motion: reduce)` | ✅ |
| Hardcoded bot client_id in invite link | Configurable via `BARK_INVITE_URL` env var | ✅ |
| Voice durations displayed as raw seconds | Added `formatDuration()` utility | ✅ |
| Members page hard-limited at 200 (silent truncation) | Paginated with "Load More" button, 100/page | ✅ |
| Settings: role IDs were text inputs | Changed to role dropdowns via `api-select` | ✅ |
| Notes: user IDs were text inputs | Changed to member search dropdown | ✅ |
| Disabled modules appeared in sidebar navigation | Filtered out in both JS and server-rendered fallback | ✅ |
| Static "Moderation" link duplicated module page | Removed from sidebar "Pages" section (handled by manifest) | ✅ |
| Settings page never showed OAuth2/invite URL status | Added "Dashboard Configuration" card | ✅ |
| Voice history showed raw user IDs | Resolves usernames from guild member cache | ✅ |
| Voice history didn't reflect channel renames | Resolves current channel name; shows ↻ indicator for renames | ✅ |
| 6 modules had raw ID text inputs in settings schemas | All role/channel fields now use `format: "role_select"` or `"channel_select"` | ✅ |
| Module docs had vague "story-based" About sections | Rewritten with "What It Does", feature descriptions, and usage | ✅ |
| AutoMod config pipeline was broken (dashboard saves went to ModuleConfig, reader read AutoModConfig) | `_get_configs()` reads ModuleConfig first (dashboard), falls back to AutoModConfig (slash) | ✅ |
| Spam detection only checked per-message mentions | Added cross-message mention rate tracking (`_check_mention_rate`) | ✅ |
| Rate limiter counted GET and POST in same bucket | Split into `_read_limiter` (3x) and `_write_limiter` (0.5x) | ✅ |
| Test Log button 404'd (no route handler) | Added `get_api_routes()` to logging module + `register_api_routes()` in module manager | ✅ |
| Module API routes never wired to FastAPI app | Added `bot.app` property + `register_api_routes()` call in `on_ready` | ✅ |
| Dropdowns lost selection after page refresh | `data-value` attribute on selects + restore in `initApiSelects()` | ✅ |
| Test Log handler had missing `Request` type hint | Added `request: Request` so FastAPI injects the request object | ✅ |

---

## Remaining Issues

### CRITICAL

**C1. Moderation module actions (test-rule, quick-warn, archive-member) POST to non-existent endpoints**

The moderation module's `get_actions()` defines three action endpoints:
- `quick-warn` → POST `/api/v1/guilds/{id}/modules/moderation/quick-warn`
- `test-rule` → POST `/api/v1/guilds/{id}/modules/moderation/test-rule`
- `archive-member` → POST `/api/v1/guilds/{id}/modules/moderation/archive-member`

None of these routes exist. The module has no `get_api_routes()` override and there are no standalone route files. The frontend submits the form and gets a 404, which translates to "❌ Failed" in the UI.

**Fix:** Add `get_api_routes()` to the moderation module (similar to the logging module fix), with handlers for all three actions. Each handler should delegate to the existing service layer methods.

---

### HIGH

**H1. Module "Reload" button doesn't reload Python code**

The dashboard's module reload button calls `/api/v1/guilds/{id}/modules/{name}/reload`, which calls `module_manager.reload_module(name)`. This only calls `disable()` then `enable()` on the **existing Python instance**. Any changes to the module's `.py` file are not picked up. A full server restart is required for code changes to take effect.

This is inconsistent with user expectations — "Reload" should mean "reload from disk."

**Fix:** Use `importlib.reload()` to re-import the module before re-enabling:
```python
async def reload_module(self, name: str) -> bool:
    import importlib

    pkg_path = f"modules.{name}.module"
    if pkg_path in sys.modules:
        importlib.reload(sys.modules[pkg_path])
    # Re-discover and re-enable
    await self.disable_module(name)
    self.discover()
    return await self.enable_module(name)
```

Note: This requires the module to be a proper package with `__init__.py` and careful cleanup of the old instance.

---

### MEDIUM

**M1. `ignored_roles` / `ignored_channels` in AutoMod rules are JSON textareas**
The AutoMod rule settings render `ignored_roles` and `ignored_channels` as textarea fields with JSON array placeholders (`["role_id_1", "role_id_2"]`). These should be multi-select dropdowns populated from the guild's roles and channels.

**M2. `auto_role_ids` in roles module is a JSON textarea**
Same issue — the auto-roles list is a textarea field requiring JSON array input.

**M3. API response shapes still inconsistent in some endpoints**
The moderation API routes use `api_paginated()` for cases but `api_success()` for warnings/notes/voice. Frontend code has to handle both `data.items` and `data.warnings` / `data.notes` / `data.sessions`.

---

### LOW

**L1. Command factories create new decorated functions on every enable**
Each call to `enable_module()` re-executes `@discord.app_commands.command(...)` decorators inside every `_make_*_command` factory, creating new command objects. Old ones leak. Over many reload cycles, this causes incremental memory growth.

**L2. vc_move reuses `duration` request field as channel ID**
The vc_move executor takes the channel ID from `data.get("duration")`, meaning the frontend must send the target channel ID in a field named "duration". This is confusing for API consumers.

**L3. No search across cases/warnings/notes**
The moderation page has pagination but no text search. Finding a case by reason or target requires flipping through pages.

**L4. `README.md` still references old architecture and setup**
The README hasn't been updated to reflect the module system, OAuth2 setup, or env var configuration.

---

## Module Inventory

| Module | Version | Commands | Events | Dashboard Pages | Has API Routes? | Actions Work? |
|--------|:---:|:---:|:---:|:---:|:---:|:---:|
| Moderation | 3.1.0 | 16 | 3 | 1 | ❌ Missing | ❌ 3/3 404 |
| Community | 2.0.0 | 10 | 4 | 1 | ❌ None needed | N/A |
| Logging | 3.0.0 | 3 | 6 | 1 | ✅ Fixed | ✅ Works |
| Post | 1.0.0 | 1 | 1 | 1 | Standalone route | ✅ Works |
| Roles | 2.1.0 | 4 | 3 | 1 | Standalone routes | ✅ Partial |
| Verification | 1.0.0 | 3 | 3 | 1 | Standalone routes | N/A |

---

## Production-Readiness Assessment

**Verdict: BETA — usable with known limitations**

### Passes
- ✅ Dashboard renders and is interactive
- ✅ Server survives bad bot token (gather with return_exceptions)
- ✅ Disabling modules is safe (handler-specific unsubscribe)
- ✅ Bot permission checks on moderation actions
- ✅ CSP allows inline scripts
- ✅ Rate limiting separates reads from writes
- ✅ OAuth2 auth with first-user-as-owner
- ✅ Module config saves actually work (pipeline fixed)
- ✅ Role/channel/member dropdowns everywhere IDs were needed
- ✅ Voice history shows usernames and live channel names
- ✅ Anti-spam tracks across channels, cross-message mention rate limiting
- ✅ Test Log button works (route handler + request type hint)

### Fails
- ❌ **Moderation "Test Rule", "Quick Warn", "Archive Member" buttons 404** — no route handlers
- ❌ **Module "Reload" doesn't reload Python code** — only re-enables the existing instance
- ❌ **No API/integration tests** — 29 unit tests, zero httpx integration tests

### Estimated effort to "Stable"
- C1 (moderation action routes): ~30 min
- H1 (Python code reload): ~15 min
- M1/M2 (multi-select dropdowns): ~1 hour
- Integration tests: ~3 hours

**Total: ~5 hours to move from Beta to Stable.**
