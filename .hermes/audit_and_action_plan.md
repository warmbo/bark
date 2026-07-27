# Bark Moderation — Audit & Action Plan

## 1. Changes Completed

### Architecture
| Change | Files |
|---|---|
| RuleSet + Rule + WordList database models | `database/models/ruleset.py` |
| Ruleset engine with trigger/condition/effect dispatch | `modules/moderation/ruleset_engine.py` |
| Extra tabs mechanism for module workspace | `modules/base.py`, `dashboard/routes/web/modules.py`, `pages/module_detail.html` |
| Welcome module (greet/leave/DM) | `modules/welcome/module.py` |
| Scam protection config per-guild | `modules/moderation/module.py` (settings schema), `ruleset_engine.py` |

### Bug Fixes
| Issue | Fix |
|---|---|
| `from __future__ import annotations` broke `Request` injection → 422 | Moved `from fastapi import Request` to module level |
| Starlette route conflict on 5-segment paths → 422 | Moved ruleset/wordlist routes to `/guilds/{id}/rulesets`, `/guilds/{id}/wordlists` |
| Ruleset type-check no-op (`isinstance(x, type(y))`) | Changed to `isinstance(x, discord.Member)` |
| Ruleset cached `[]` before seeding default | Moved seed call before cache write, re-query after |
| Missing `UniqueConstraint` on RuleSet | Added `__table_args__` |
| Voice channel moves not tracked | Added channel-change branch to voice handler |
| `_json_dict` used on array-typed scoped conditions | Added `_json_list`, swapped all array fields |
| Silent `except: pass` swallowing errors | Replaced with `logger.exception()` |
| Dashboard warn always crashed (`_exec_warn` wrong sig) | Added `duration=None` parameter |
| Badge XSS (unescaped values in HTML class attributes) | Added `.replace(/[^a-z0-9_-]/g,'')` + `escHtml()` |
| Dashboard actions bypassed Discord permissions | Added actor guild member + permission check |
| Dashboard actions had no role hierarchy check | Added top-role comparison |
| `/automod` wrote to orphaned table | Added ruleset detection + deprecation message |
| Logging module silent failures on send | Added `logger.warning()` |
| Notes API response path wrong | Added `raw.data?.notes` fallback |
| Test Rule only checked legacy config | Added ruleset check |
| Dead `_cmd_action_*` methods | Removed 60 lines of dead code |
| Input validation on `target_id` | Added try/except ValueError |
| Inline `onclick` handlers | Replaced with event listeners |
| DOMContentLoaded race in extra tab scripts | Added `document.readyState` guard |
| Lucide icons not rendering in dynamic content | Added `lucide.createIcons()` call |
| Nav highlighting broken after URL merge | Updated `PageRegistration` route |
| `guild_id: int` in module API routes | Changed to `str` with explicit `int()` |

### UI
| Feature | Location |
|---|---|
| Module workspace with 9 tabs | `pages/module_detail.html` + 6 tab templates |
| Ruleset editor (full: create/edit/delete rules, conditions) | `module_tabs/moderation_rulesets.html` |
| Word list editor (full: create, expand rows, edit entries, delete) | `module_tabs/moderation_wordlists.html` |
| Cases/Warnings/Notes/Voice tab views | `module_tabs/moderation_{cases,warnings,notes,voice}.html` |
| Quick Setup presets (New Account Shield, Scam, Raid) | Rulesets tab |
| `/guild/{id}/moderation` → `/guild/{id}/modules/moderation` redirect | `dashboard/routes/web/moderation.py` |
| Right-side slide-in panel for rule editing | Rulesets tab |
| Confirm/prompt modals (no browser dialogs) | Rulesets tab, Word Lists tab |

### Trigger types (11 core)
`message_spam`, `mass_mention`, `invite_link`, `banned_words`, `banned_domains`, `scam_link`, `regex_match`, `duplicate_message`, `all_caps`, `attachment_spam`, `any_link`

### Effect types (7)
`warn`, `delete`, `timeout`, `kick`, `ban`, `alert`, `delete_multiple`

---

## 2. Verified Working

- [x] All 9 module workspace tabs render and load data
- [x] Cases table with pagination
- [x] Warnings table
- [x] Notes: add, save, list
- [x] Rulesets: create, rename, toggle, add rule, edit rule, delete rule, delete ruleset, conditions (account age, ignore bots)
- [x] Word Lists: create, expand/edit entries, save, delete
- [x] Voice History: load session list
- [x] Quick presets: all 3 create rulesets with conditions + rules
- [x] Right-side rule editor panel: opens/closes, saves trigger + effect + conditions
- [x] `/guild/{id}/moderation` redirects to module workspace
- [x] Nav highlights "Moderation" when on page
- [x] 69/71 tests pass (2 pre-existing failures from removed modules)
- [x] Ruleset engine compiles and dispatches triggers/effects correctly
- [x] Scam domains configurable per-guild (Configure tab)
- [x] Welcome module: join/leave messages, DMs, `/welcome` command

---

## 3. Remaining Issues

### High Priority
| # | Issue | Location | Impact |
|---|---|---|---|
| H1 | Word list ID not selectable from dropdown in rule editor | Rulesets tab trigger config | Users must know the numeric list ID to use banned_words/banned_domains triggers |
| H2 | Rule editor doesn't show available word lists | Rulesets tab | No way to discover which lists exist or their IDs |
| H3 | No way to assign a role-mute (role-based mute, not Discord timeout) | Missing feature | Timeouts expire at 28-day Discord limit—role mutes have no limit |
| H4 | `mutation_capability` returns `"moderation.manage"` for ruleset/wordlist endpoints but no such permission is registered | `services/security.py` | Falls back to `"admin"`—only admins can manage rulesets (may be intentional) |

### Medium Priority
| # | Issue | Location | Impact |
|---|---|---|---|
| M1 | `/automod` slash command creates dead records in `AutoModConfig` table | `module.py:_cmd_automod` | Orphaned data, confusing for pre-migration users |
| M2 | LogConfig DB model dead (never read) | `database/models/logging.py` | Dead table, dead test, confusing for developers |
| M3 | Case number race condition (`MAX+1` concurrent) | `moderation_service.py`, `ruleset_engine.py` | Rare DB constraint violation under concurrent moderation |
| M4 | Wordlist cache has no TTL | `ruleset_engine.py:_get_list_entries` | Out-of-process changes invisible until module reload |
| M5 | Cleanup loop hardcodes 2-min cutoff | `module.py:_cleanup_loop` | Rules with >2min windows have data pruned mid-detection |
| M6 | Cleanup loop can crash on TypeError from attachment tracker | `module.py:_cleanup_loop` | Entire cleanup task dies, memory leak until restart |
| M7 | `_mention_track` in AntiRaidService never pruned | `module.py:_cleanup_loop` | Small memory leak over time |
| M8 | Dashboard unban route skips actor permission/hierarchy checks | `actions.py:action_unban` | Inconsistent with other dashboard actions |
| M9 | Ruleset `content_spam` alias points to exact-duplicate instead of fuzzy-similarity | `ruleset_engine.py` | Migrated legacy rules behave differently |
| M10 | Bot messages discarded before moderation handler runs | `bot/client.py:on_message` | `only_bots` rules and webhook scam detection never fire |
| M11 | Ruleset processing doesn't create moderation cases for punitive effects | `ruleset_engine.py:_effect_kick,_effect_ban` | No audit trail for AutoMod kicks/bans |
| M12 | Tests missing for ruleset engine, welcome module, logging event handlers | `tests/` | No automated verification |

### Low Priority
| # | Issue | Location |
|---|---|---|
| L1 | `discord.Member` annotation in `_effect_timeout` uses TYPE_CHECKING-only import | `ruleset_engine.py` |
| L2 | `_check_duplicate_message` has dead `hasattr(module, "_dup_track")` guard | `ruleset_engine.py` |
| L3 | `SequenceMatcher` imported inside loop in legacy `_check_content_spam` | `module.py` |
| L4 | Log files endpoint creates >25 embed fields | `logging/module.py` |

---

## 4. Action Plan

### Phase 1 — Fix the blocker (1 session)
**Objective:** Make `banned_words`/`banned_domains` triggers usable.

- Add a word-list dropdown selector to the rule editor that fetches available lists from the API and populates a `<select>` with list names → `word_list_id`
- Show list type (word/domain) next to each option
- Make the dropdown required when trigger is `banned_words` or `banned_domains`

### Phase 2 — Hardening (1 session)
**Objective:** Fix the highest-impact reliability issues.

| Item | Fix |
|---|---|
| H3 — Role-based mute | Add `/mute` command + `_effect_mute` that manages a Muted role with timed auto-removal |
| M3 — Case number race | Centralize all case creation in `ModerationService` with retry-on-conflict |
| M5 — Cleanup cutoff | Derive retention from max configured rule window |
| M6 — Cleanup TypeErrors | Add per-tracker try/except, log failures |
| M11 — AutoMod audit trail | Create moderation cases from ruleset kick/ban effects |

### Phase 3 — Audit and test coverage (1 session)
**Objective:** Fill critical test gaps.

- Ruleset engine unit tests (trigger dispatch, condition checking, effect execution)
- Welcome module integration tests (event handler, config load, template rendering)
- Logging module event handler tests
- API endpoint tests for all module routes
- Permission/hierarchy tests for dashboard actions

### Phase 4 — Polish (1 session)
**Objective:** Clean up residual technical debt.

| Item | Fix |
|---|---|
| M1 — `/automod` deprecation | Already partially done — add DB migration warning or full removal |
| M2 — LogConfig dead model | Remove ORM model, dead test, update README |
| M8 — Unban auth | Route unban through `_mod_action` common path |
| M9 — content_spam alias | Fix to point to fuzzy similarity checker |
| M10 — Bot message filtering | Move bot/webhook filter from bridge to ruleset conditions |
| M12 — All low-priority items | Fix each in isolation |

### Phase 5 — Feature completion (future)
**Objective:** Features that would complete the moderation system.

- Role-based mute system (override Discord's 28-day timeout limit)
- Appeal workflow (users can submit appeals via dashboard)
- Moderation dashboard widgets (recent activity, action stats)
- Export/import ruleset configurations
- Audit log integration for AutoMod actions (log to Discord channel)
