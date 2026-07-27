# Discord Moderation Dashboard — Desktop UI/UX and Visual Audit Plan

Created: 2026-07-16
Status: Baseline audit complete; implementation not started
Scope: Bark dashboard shell, shared UI, all first-party pages, and Community, Logging, Moderation, Post, Roles, and Verification modules

## Objective

Turn Bark into a cohesive desktop management application rather than a collection of server-rendered pages. Preserve its FastAPI/Jinja architecture, sharp-corner dark glass visual language, and dashboard-first module system while making navigation, forms, data views, feedback, permissions, and Discord integration predictable everywhere.

This plan is deliberately desktop-first. Responsive desktop resolutions, zoom, reduced motion, and keyboard use are required; a mobile-first redesign and deep moderation case/appeal tooling are not.

## Baseline audit evidence

Current implementation inventory:

- 11 Jinja page/partial templates and a shared `base.html` shell.
- One approximately 1,930-line dashboard stylesheet.
- Four dashboard JavaScript files: `main.js`, `palette.js`, `realtime.js`, and `shortcuts.js`.
- Six first-party modules exposed through a generic module-detail renderer.
- One reusable Jinja component macro file, currently focused on icons rather than complete controls.
- 16 inline `<script>` blocks and 24 inline `onclick` handlers across current templates.
- 20 rendered form controls but only four explicit labels and three `aria-label` attributes in the audited template markup.
- 21 direct `fetch()` call sites in templates alongside a separate `safeFetch()` helper and a separate `loadSection()` implementation.
- 36 `backdrop-filter` declarations and many raw pixel/color literals in a monolithic stylesheet.
- Responsive rules at broad desktop and small-screen boundaries, but no automated browser matrix or visual regression suite.
- Existing API tests cover core routes, access, module toggle behavior, and manifest shape, but not rendered-page accessibility, keyboard behavior, cross-module action contracts, or visual layout.
- Audit verification found 61 tests passing; those tests do not cover action-manifest endpoint resolution, configuration-source convergence, verification challenge execution, role-menu reactions, scheduler delivery failure, fresh-config enabled state, or module-action RBAC.

Representative source surfaces:

- Shell and fallback navigation: `dashboard/templates/base.html`
- Shared styling: `dashboard/static/css/main.css`
- Generic controls and request helpers: `dashboard/static/js/main.js`
- Palette and shortcuts: `dashboard/static/js/palette.js`, `dashboard/static/js/shortcuts.js`
- Realtime state: `dashboard/static/js/realtime.js`
- Generic module renderer: `dashboard/templates/pages/module_detail.html`
- Modules index: `dashboard/templates/pages/modules.html`
- Guild overview: `dashboard/templates/pages/guild.html`
- Members and moderation workspaces: `dashboard/templates/pages/members.html`, `member_detail.html`, `moderation.html`
- Settings: `dashboard/templates/pages/settings.html`

## Prioritized issue register

### P0 — Trust and integration blockers

These precede visual polish because a premium UI cannot compensate for controls that save to the wrong source, actions that do not execute, or status that lies.

#### INT-01 — Module configuration does not have one authoritative contract

- Logging dashboard settings are module settings, while slash commands and runtime status use `LogConfig` rows.
- Verification similarly exposes generic module settings while runtime behavior also uses dedicated verification configuration.
- Settings and module pages can therefore display a value that is not the value the bot executes.
- Why it matters: users lose trust after a successful-looking save does not change Discord behavior.
- Improvement: define one authoritative typed configuration service per module; make dashboard, commands, runtime handlers, health checks, and status displays read/write through it.
- References: `modules/logging/module.py:134-207`, `modules/verification/module.py:76-145`, `dashboard/routes/api/modules.py`.

#### INT-02 — Shared schema serialization and validation are incomplete

- Generic array fields are submitted from HTML forms as strings while modules such as Moderation and Roles expect arrays/objects.
- Labels, defaults, dependencies, minimum/maximum, URL/date/time semantics, and nested schema behavior are inconsistently enforced server-side.
- Improvement: build a typed schema adapter with explicit serializers, server validation, field-path errors, and normalized API responses.
- References: `dashboard/templates/pages/module_detail.html`, `dashboard/routes/api/modules.py`, `modules/moderation/module.py:185-197`, `modules/roles/module.py:155-204`.

#### INT-03 — Roles exposes dead or incomplete dashboard workflows

- The generic action model includes reaction-role and role-menu actions, but endpoint naming and available routes are not consistently aligned.
- Stored reaction mappings and temporary expirations are not yet represented as a durable, inspectable dashboard workflow.
- The role-menu action asks users to edit JSON instead of using native role rows.
- Improvement: reconcile action IDs/routes; persist expirations; provide list/edit/delete/test operations; validate role hierarchy and permissions before execution.
- References: `modules/roles/module.py:150-218,622-697`, `dashboard/routes/api/role_manager.py`, `dashboard/routes/api/reaction_roles.py`.

#### INT-04 — Verification completion paths are not reliable enough for a setup UI

- Button, emoji, and agreement paths do not yet share a single completion/state contract.
- Persistent interactive views and deleted-message/channel recovery need explicit startup reconciliation.
- Improvement: unify challenge handlers, make role transitions transactional/idempotent, restore persistent views, and report stale resources in module health.
- References: `modules/verification/module.py:137-460`, `dashboard/routes/api/verification.py`.

#### INT-05 — Post delivery status can be misleading

- Missing resources and repeat failures need durable terminal states, bounded retry/backoff, and operator-visible errors.
- Improvement: use queued/sending/sent/retrying/failed/cancelled states, attempt counts, next-attempt timestamps, and explicit Discord error details.
- References: `modules/post/module.py:142-287`, `database/models/post.py`, `dashboard/routes/api/post.py`.

#### INT-06 — Moderation detection and dashboard actions are internally fragmented

- `ModerationModule` defines `get_actions()` twice; the later definition overrides quick-warn/test-rule actions.
- Spam, repeated-content, bot/webhook, and anti-raid settings must be traced end-to-end before exposing confident status.
- Improvement: consolidate action registration, test every rule path with schema settings, and keep scope focused on spam prevention and hacked-profile indicators rather than deep case/appeal management.
- References: `modules/moderation/module.py:199-246,1013-1047`, `services/anti_raid.py`, `bot/client.py`.

#### INT-07 — Community has recoverability edge cases

- XP range handling must be valid when message XP is zero.
- Existing connected voice members need to be seeded after module enable/reload.
- Invite attribution and synchronization should have explicit unknown/error states.
- Improvement: normalize XP bounds, recover active voice sessions, serialize invite attribution per guild, and expose last-sync health.
- References: `modules/community/module.py:108-138,401-457`.

#### INT-08 — UI status does not always represent live state

- The sidebar footer presents a static connected state.
- Static fallback navigation and asynchronous manifest hydration can briefly disagree.
- Guild overview uses grouped loads where one endpoint failure can prevent unrelated healthy sections from updating.
- Improvement: introduce a shared health/status store sourced from health, manifest, and SSE data; isolate section failures.
- References: `dashboard/templates/base.html`, `dashboard/templates/pages/guild.html`, `dashboard/static/js/realtime.js`.

#### INT-09 — Saving fresh module settings can silently disable the module

- When no `ModuleConfig` exists, the settings API creates one with `enabled=False`, while the module page and list initially render that module as enabled.
- The save does not reconcile `ModuleManager._guild_states`; the page, database, runtime, manifest, and post-restart state can all disagree.
- Why it matters: a normal configuration save can deactivate any of the six modules after restart without telling the operator.
- Improvement: preserve the effective enabled state when creating configuration and update runtime/database state atomically.
- Acceptance: `fresh module → save configuration → remains enabled` immediately and after restart; page, manifest, database, and `is_enabled_for_guild()` agree.
- References: `dashboard/routes/api/modules.py:81-83,130-145`, `dashboard/routes/web/modules.py:90-96`.

#### INT-10 — Guild identifiers have incompatible meanings

- Discord-facing code passes Discord snowflakes as `guild_id`, while several feature models define `guild_id` as a foreign key to the internal autoincrement `guilds.id`; `ModuleConfig` separately stores a Discord ID string.
- Why it matters: module records can become orphaned, invisible, or joined to the wrong guild, undermining every cross-module dashboard view.
- Improvement: select one canonical persistence contract—prefer an internal guild foreign key plus a mandatory snowflake resolver, or consistently persist `discord_id`; migrate existing data and enable foreign-key checks.
- Acceptance: every module/API round-trips data for a nontrivial snowflake and resolves the same internal guild.
- References: `database/models/guild.py:16-18`, `database/models/module.py:13-22`, `database/models/verification.py:16-24`, `bot/client.py:158-168`.

#### INT-11 — Generic action booleans can invert destructive intent

- Action fields declared as `boolean` fall through to `<input type="boolean">`, which browsers treat as text, and action serialization reads `.value` instead of checkbox state.
- This affects Moderation maintenance fields such as `dry_run` and `keep_active`.
- Why it matters: an operator can believe an archive/purge is a dry run while the backend receives a misleading truthy string or default.
- Improvement: render native labeled checkboxes, serialize `.checked` as a JSON boolean, and require a danger confirmation that explicitly summarizes scope and dry-run state.
- References: `dashboard/templates/pages/module_detail.html:178-190,402-405`, `modules/moderation/module.py:1013-1045`.

#### INT-12 — General Settings can overwrite persisted values with defaults

- The page hardcodes prefix `!` and blank roles, never calls the existing read endpoint, then submits every displayed value.
- Why it matters: opening Settings and saving can erase an existing prefix or moderator/admin role assignment.
- Improvement: load authoritative values before enabling Save, coordinate role-option hydration with selected values, show retryable initialization failure, and make untouched saves no-ops.
- References: `dashboard/templates/pages/settings.html:99-144`, `dashboard/routes/api/settings.py:64-75`.

#### INT-13 — Privileged mutations lack consistent action-level RBAC

- Guild manageability is checked globally, but Post, Roles, Reaction Roles, Verification, Leveling, Logging, and module-action routes do not uniformly enforce permission definitions.
- The UI also renders mutations regardless of the viewer/moderator/admin capability set.
- Why it matters: users see actions they cannot perform, and some standalone write paths can be over-permissive.
- Improvement: centralize route authorization from module permission definitions; include capabilities in page/manifest data; hide or explain unavailable actions while preserving server authority.
- References: `services/security.py:56-110`, `services/response.py:24-38`, `dashboard/routes/api/post.py`, `reaction_roles.py`, `role_manager.py`, `verification.py`, `leveling.py`.

#### INT-14 — Declared realtime behavior is disconnected from module events

- The realtime bridge subscribes to AutoMod, moderation-case, and level-up events, but current modules do not emit the matching typed domain events.
- Why it matters: the shell suggests live operation while toasts and data views remain stale.
- Improvement: emit typed events only after committed state and confirmed Discord actions; update relevant counters/rows and test payload contracts end-to-end.
- References: `services/realtime_bridge.py:22-76`, `dashboard/static/js/realtime.js:58-104`, `services/event_bus.py:67-85`.

#### INT-15 — Configuration saves drop unchecked booleans and corrupt array types

- `FormData` omits unchecked checkboxes, so users cannot reliably turn off default-enabled settings and unrelated saves can omit explicit `false` values.
- Array-backed settings are rendered as textareas and persisted as strings; server validation does not enforce arrays, item types, enums, or unknown keys.
- Improvement: serialize every schema property by declared type, explicitly include `false`, use structured multi-selects where possible, JSON-parse remaining arrays with inline errors, and reject malformed payloads server-side.
- Acceptance: every module schema round-trips true, false, arrays, enums, nested values, and untouched values without type drift.
- References: `dashboard/templates/pages/module_detail.html:42-63,89-110,323-332`, `dashboard/routes/api/modules.py:216-265`.

### P1 — Design-system and component inconsistencies

#### DS-01 — Tokens do not fully define the visual system

- Typography sizes, control heights, spacing, transitions, and elevation are still frequently raw literals.
- Multiple aliases and repeated responsive overrides make the canonical value unclear.
- Improvement: define semantic tokens for typography, spacing, component height, radius exceptions, border, elevation, motion, z-index, and density. Raw values should remain only for genuine one-off geometry.

#### DS-02 — Shared components are CSS conventions, not enforceable templates

- Pages manually recreate headers, cards, filters, states, form groups, action panels, pagination, and confirmation UI.
- Improvement: add Jinja macros/partials for `app_shell`, `page_header`, `toolbar`, `card`, `form_field`, `toggle`, `select`, `status_badge`, `data_view`, `empty_state`, `error_state`, `pagination`, `dialog`, and `toast`.
- Target files: new files under `dashboard/templates/components/`; migrate all page templates.

#### DS-03 — Three action/form interaction models coexist

- Generic module action cards, member-list popovers, and member-detail injected forms each behave differently.
- Native `confirm()`, inline success text, popover replacement, and toast feedback all coexist.
- Improvement: one action-dialog contract with severity, permission preflight, validation, progress, result summary, focus restoration, and optional undo where safe.

#### DS-04 — Iconography and status semantics are inconsistent

- Server-rendered Lucide icons, dynamically generated `data-lucide` icons, emoji, text symbols, and punctuation-only action buttons are mixed.
- Status is sometimes color-only.
- Improvement: use one icon registry, pair semantic colors with icon and text, and reserve emoji for user-authored Discord previews rather than application chrome.

#### DS-05 — Page hierarchy varies by screen

- Some screens use page title/subtitle; the guild overview starts directly with metrics; module pages add a back link and metadata strip; dashboard server groups use a different heading system.
- Improvement: standardize page context as eyebrow/breadcrumb, H1, concise description, health/status, primary action, and optional secondary toolbar.

#### DS-06 — Long generic module pages become undifferentiated stacks

- Configuration, multiple actions, commands, and about content are rendered in a single vertical stream.
- Improvement: introduce a consistent module workspace: Overview, Configure, Operate, Activity, and Help. Hide unavailable sections rather than leaving empty shells.

#### DS-07 — Glass effects are over-applied

- Dozens of backdrop filters increase compositing cost and flatten visual hierarchy because nearly every surface competes for the same effect.
- Improvement: reserve blur for app shell, overlays, and elevated floating surfaces; use opaque/translucent tokenized fills for ordinary cards and tables.

#### DS-08 — CSS and page scripts are difficult to evolve safely

- `main.css` is monolithic; template-local scripts duplicate state rendering and action code.
- Improvement: split CSS by tokens/shell/components/pages/utilities and JS by API/state/components/page controllers, while retaining a small build-free ES-module architecture.

#### DS-09 — Intended motion references undefined primitives

- `--ease-out` is referenced but not declared, and `shadow-drift` is referenced without matching keyframes.
- Why it matters: selected page/nav motion can be invalid while other surfaces continue animating, creating inconsistent feedback.
- Improvement: define a small motion token set by interaction type, remove dead animation references, and test computed styles under normal and reduced motion.
- References: `dashboard/static/css/main.css:397,434,754`.

#### DS-10 — Structural sharpness is incorrectly inherited by identity primitives

- `--radius-full: 0px` makes avatars, status dots, toggle handles, chips, and badges square through one global rule.
- Improvement: keep surfaces and controls sharp while defining intentional avatar/status/pill/toggle geometry where shape carries identity or state.
- References: `dashboard/static/css/main.css:61-66,291-292,769,900,922-927,1232-1264`.

#### DS-11 — Markup declares incomplete or undefined components

- `.form-row`, `.filter-search-bar`, `.context-menu`, and `.shortcuts-help` are used without complete shared CSS; shortcut help compensates with inline styling.
- Improvement: implement each as a documented component or remove the dead markup/partial. Add a CI inventory comparing literal template classes with stylesheet definitions.
- References: `member_detail.html:169`, `members.html:14`, `base.html:153`, `shortcuts.js:50-85`.

#### DS-12 — Critical shell rendering depends on synchronous third-party assets

- Google fonts and a head-loaded Lucide CDN script can delay/degrade the shell; global icon rescans repeat after dynamic rendering.
- Improvement: self-host/subset assets where practical, defer scripts, prefer server-rendered SVG, and initialize only newly inserted icons.
- References: `dashboard/templates/base.html:12-15,159`, `dashboard/static/js/palette.js:188-201`.

### P1 — UX and desktop workflow inconsistencies

#### UX-01 — Navigation is generated twice

- `base.html` ships fallback guild navigation, then `main.js` replaces it from the manifest.
- Labels, icons, active states, enabled state, and ordering can flash or drift.
- Improvement: render the manifest server-side for first paint and use the same payload for palette/navigation updates.

#### UX-02 — Navigation still behaves like a traditional website

- Most links and palette selections trigger full document loads; scroll, tab, and work context are discarded.
- Improvement: after extracting inline page controllers, add progressive same-origin app-shell navigation with History API, main-region replacement, title/breadcrumb updates, focus management, and hard-navigation fallback.
- Do not rewrite Bark as a SPA.

#### UX-03 — Desktop context is underdeveloped

- Persistent navigation exists, but there is no consistent context toolbar, breadcrumb, recent destination list, or cross-page action area.
- Improvement: add a compact top context bar containing guild switcher, breadcrumb, connection health, command palette affordance, and page actions.

#### UX-04 — Moderation work is split across unrelated locations

- Cases/warnings/notes/voice history live on the Moderation page; AutoMod configuration and generic module actions live on the module page; member actions use two additional patterns.
- Improvement: make Moderation one workspace with Overview, Protection, Members, Activity, and Settings; link to member detail using a retained side panel or return state.

#### UX-05 — Common actions require too much reorientation

- Opening a member, taking action, returning to filtered members, and reviewing outcomes causes page changes or custom popovers.
- Improvement: preserve filters and scroll, open member context in a side inspector at desktop widths, and refresh affected rows/SSE counters in place.

#### UX-06 — Command palette advertises actions but mainly navigates

- Palette actions open pages rather than executing a guided operation, and the palette cache is not scoped/reset robustly across guild changes.
- Improvement: distinguish Navigate and Run groups; launch standardized dialogs for safe actions; show current guild; invalidate data on manifest/guild changes.

#### UX-07 — Keyboard support is incomplete and partially hidden

- `?` opens an inline-styled pseudo-dialog labeled as future work.
- Tabs lack arrow/Home/End behavior.
- Many dynamically generated action controls rely on inline click handlers.
- Improvement: implement a real shortcuts dialog, roving tab index for tabs/menus, visible shortcut hints, consistent Escape behavior, and no keyboard traps.

#### UX-08 — Draft and unsaved-change behavior is unreliable

- Generic module detail uses a native confirmation prompt.
- `persistForm()` clears a draft shortly after submit regardless of confirmed success.
- Improvement: centralize dirty state, clear only after successful API acknowledgement, provide Save/Discard, and identify the changed section.

#### UX-09 — Loading, empty, error, and success states are fragmented

- Some views show skeleton cards, others text, some expose raw exception messages, and many errors have no retry action.
- Improvement: create state primitives with appropriate icon, plain-language reason, retry/repair action, and retained previous data for background refreshes.

#### UX-10 — Tables and cards are not one data-view system

- Moderation uses tables; members use cards; settings and module operations use stacked cards; sorting/filtering/pagination patterns differ.
- Improvement: define a desktop data-view contract with toolbar, query state, count, sort, column behavior, pagination, row actions, and compact-card fallback.

#### UX-11 — Filters are not self-describing or persistent enough

- Member search and selects depend on placeholders/options rather than visible labels.
- Improvement: visible or accessible labels, active-filter chips, URL query synchronization, saved state per guild, and one Clear action.

#### UX-12 — Settings mixes product, guild, and deployment concepts

- General guild settings, module state, and dashboard/infrastructure settings appear in one page without a clear permission or ownership boundary.
- Improvement: separate Server Settings, Module Defaults, Dashboard Preferences, and owner-only System Settings; hide inaccessible sections rather than disabling unexplained controls.

#### UX-13 — Member quick-action confirmations are clipped by their cards

- Popovers are appended below member cards, but cards use `overflow: hidden`.
- Why it matters: warn/timeout/kick/ban confirmation can be partly or completely invisible.
- Improvement: render through a viewport-level anchored popover/dialog layer with collision detection, Escape/outside-click handling, focus entry, and focus restoration.
- References: `dashboard/templates/pages/members.html:146-163`, `dashboard/static/css/main.css:728-740,865-879`.

#### UX-14 — Member search can display stale out-of-order results

- Search requests use timestamped URLs, so shared cancellation does not identify them as the same logical query; slower old responses can overwrite newer filters and counts.
- Improvement: use a page-scoped AbortController or monotonically increasing request token and ignore stale settlements.
- References: `dashboard/templates/pages/members.html:80-85,207-225`, `dashboard/static/js/main.js:15-18`.

#### UX-15 — Palette quick actions do not open the named action

- Manifest actions point to the module root even though action cards have anchors.
- Why it matters: selecting Compose, Quick Warn, or Test Log still leaves the operator searching and scrolling.
- Improvement: deep-link to `#action-{id}` or launch the shared action dialog directly; focus the destination and exclude disabled/inaccessible actions.
- References: `dashboard/routes/api/manifest.py:126-133`, `dashboard/static/js/palette.js:67-77`, `dashboard/templates/pages/module_detail.html:143-151`.

#### UX-16 — Member investigation loses list context

- Member query, filters, sort, loaded page, and scroll position live only in DOM/global state; the detail Back link carries no state.
- Improvement: synchronize filters with URL/history state, restore scroll/member position, and use a desktop side inspector where space permits.
- References: `dashboard/templates/pages/members.html:58-83,207-225`, `member_detail.html:7-10`.

#### UX-17 — Desktop member scanning and table overflow are poorly matched to workstation use

- Members default to a fixed three-column centered card grid, while moderation tables sit inside overflow-hidden cards and body overflow is globally hidden.
- Improvement: use a compact row/table as the desktop default with optional card view; add labeled horizontal table regions, minimum widths, sticky headers, and column priority rules.
- References: `dashboard/static/css/main.css:107-115,609-617,722-823,1292-1329`, `moderation.html:135-147,174-185,284-296`.

#### UX-18 — Desktop breakpoints are viewport-based rather than workspace-aware

- Fixed sidebar width means viewport breakpoints do not represent actual content space; forms can stretch near the full 1400px maximum while narrow desktops retain dense grids.
- Improvement: introduce container-aware compact/standard/large/wide workspace tiers; constrain form reading width and use intentional two-column groups.
- References: `dashboard/static/css/main.css:72-76,230-245,422-433,645-655,1891-1899`.

### P1 — Accessibility defects

#### A11Y-01 — Labels are not programmatically associated

- Many `form-label` elements omit `for`, and controls generated in scripts are similarly unlabeled.
- Improvement: every control gets a stable ID, label, description association, error association, and required semantics.

#### A11Y-02 — Tabs are only visually stateful

- Current tab buttons omit `aria-selected`, `aria-controls`, managed tabindex, and keyboard behavior; panels omit full tabpanel relationships.
- References: `dashboard/templates/pages/moderation.html:33-111`, `dashboard/static/js/main.js:139-181`.

#### A11Y-03 — Dynamic dialogs/popovers are not real dialogs

- Member quick actions and shortcut help do not consistently expose dialog semantics, focus containment, initial focus, or focus restoration.
- Improvement: one accessible dialog/popover implementation; destructive actions require an explicit title, consequence, and target.

#### A11Y-04 — Icon-only controls have weak names

- Several moderation/member controls use symbols and `title` only.
- Improvement: visible text where space permits; otherwise `aria-label` plus tooltip and 32–36px desktop target.

#### A11Y-05 — Dynamic state announcements are inconsistent

- Toasts have live-region semantics, but loaders, results, table counts, validation, and background reconnect status do not.
- Improvement: polite status region for loading/results and assertive alerts only for blocking errors.

#### A11Y-06 — Contrast, zoom, reflow, and reduced motion lack automated gates

- Focus styles and reduced-motion CSS exist, but no current automated audit proves all states.
- Improvement: add axe checks, keyboard flows, 200% zoom/reflow checks, and reduced-motion screenshots to the QA matrix.

### P2 — Module-specific product gaps

#### MOD-COMMUNITY

- Add a real module workspace rather than only generic settings/actions.
- Overview: leveling participation, invite sync health, unattributed joins, recent level-ups.
- Operate: leaderboard search/reset/adjust, reward-role CRUD, invite attribution review.
- Configure: Discord message previews and permission checks for announcement destinations.
- Reliability: valid XP bounds, voice-session recovery, serialized invite attribution.
- Replace the synthetic guild `0` invite-sync interval with an explicit global interval or true per-guild scheduling.

#### MOD-LOGGING

- Unify configuration storage first.
- Show each event type as a status row with destination, enabled state, last delivery, and last error.
- Add Test destination at row and module level.
- Detect deleted channels and missing send/embed permissions.
- Add event-volume indicators without creating a heavyweight analytics product.
- Ensure Dashboard, `/logsetup`, `/logstatus`, event delivery, and Test Log all use the same repository and display identical state.

#### MOD-MODERATION

- Keep focus on spam prevention, hacked-profile signals, and essential member actions.
- Protection overview: rule state, recent triggers, false-positive controls, dry-run/test mode.
- Add hacked-profile heuristics such as sudden outbound-link bursts and abnormal repeated messages, with explainable signals.
- Pass configured anti-raid threshold/window into detection instead of service defaults; make webhook/scam analysis reachable without counting normal bot traffic as user spam.
- Consolidate duplicate actions and use one member-action dialog.
- Do not add deep appeals, legalistic case workflows, or complex manual review queues.

#### MOD-POST

- Replace a generic action form with a composer workspace.
- Left: draft/scheduled history; center: fields; right: Discord-style preview.
- Use native date/time controls, explicit timezone, repeat summary, validation against Discord embed limits, and image preview.
- Expose delivery status, retry/cancel/edit/duplicate operations, and terminal failures.
- Make exposed default channel/color/author settings populate and affect compose output; display an explicit timezone, convert safely across DST, and use calendar-month rather than fixed 30-day recurrence.

#### MOD-ROLES

- Replace JSON textareas and message IDs where possible with structured builders and resource selectors.
- Show current reaction bindings, role menus, auto roles, conditional roles, and temporary assignments in data views.
- Validate Bark role hierarchy and block managed/integration/administrator role hazards.
- Add repair states for deleted messages, channels, emojis, and roles.
- Reconcile or remove settings that have no runtime consumer, including schema auto-role IDs, remove-old-reaction behavior, and menu cleanup without a message-delete event.

#### MOD-VERIFICATION

- Replace generic configuration with a guided setup/checklist.
- Steps: choose challenge, choose pending/verified roles, choose channel/message, permission preflight, preview, test, activate.
- Show funnel metrics: started, completed, expired, failed.
- Provide repair actions for stale resources and persistent-view recovery.
- Prove button, emoji, and agreement paths each grant only the verified role, remove pending, report actual failure, survive restart, and create exactly one attempt record.

## Implementation phases

### Phase 0 — Freeze the baseline and install audit gates

Goal: make each later iteration measurable and prevent visual/behavioral regressions.

Tasks:

1. Preserve the current dirty workspace; do not reformat or overwrite unrelated work.
2. Add a UI test harness under `tests/ui/` using Python Playwright and axe integration as development dependencies in `pyproject.toml`.
3. Add authenticated fixture data covering all server tiers, every module enabled/disabled, long names, no-data/error/loading states, missing permissions, and stale Discord resources.
4. Test desktop viewports: 1024×768, 1280×800, 1440×900, 1920×1080, and 2560×1440.
5. Add 200% zoom, reduced-motion, keyboard-only, and offline/API-failure scenarios.
6. Create `docs/dashboard-audit-register.md` with issue ID, severity, owner, phase, evidence, status, verification, and screenshot links.
7. Record baseline task measurements:
   - open a guild and module setting;
   - warn/timeout a member;
   - find a moderation trigger;
   - schedule a post;
   - create a role binding;
   - configure verification.

Acceptance criteria:

- Browser harness runs locally and in CI.
- Every first-party page and module has a smoke test and screenshot artifact.
- Axe critical/serious findings are captured rather than waived silently.
- Console errors, failed network calls, overflow, and unhandled promise rejections fail tests.
- Baseline audit register contains every issue in this plan.

### Phase 1 — Restore behavioral trust

Goal: ensure every visible status, save, and action maps to real bot behavior.

Primary files:

- `modules/{community,logging,moderation,post,roles,verification}/module.py`
- `dashboard/routes/api/modules.py`
- Module-specific API routes under `dashboard/routes/api/`
- Relevant database models and services
- New contract/integration tests under `tests/test_modules/` and `tests/test_dashboard/`

Tasks:

1. Resolve INT-01 through INT-15, beginning with fresh-save disablement, guild-ID normalization, destructive boolean serialization, Settings initialization, and mutation RBAC.
2. Define typed module settings/action results with field errors and health diagnostics.
3. Add endpoint/action contract tests generated from each module’s declared actions.
4. Add module health payload: enabled, configured, permissions, resources, last success, last error, queue/backlog.
5. Make async operations idempotent and represent pending/retry/failed states.
6. Prevent the UI from claiming success until the authoritative service confirms it.

Acceptance criteria:

- Dashboard, slash command status, and runtime handlers return the same effective configuration.
- Saving a new or existing module configuration preserves its enabled state immediately and after restart.
- Every persisted module record resolves through the canonical guild identifier contract.
- General Settings cannot submit until authoritative values and resource options have loaded; untouched save is a no-op.
- Viewer/moderator/admin mutation matrices are enforced in both rendered capabilities and server routes.
- Every declared module action has a reachable authorized route and contract test.
- No visible successful save can be followed by unchanged runtime behavior.
- Health identifies deleted resources and missing permissions with a repair path.
- P0 module reliability tests pass.

Audit gate: repeat full Phase 0 matrix; compare action outcomes in UI, API, database, and Discord mock.

### Phase 2 — Establish the enforceable design system

Goal: replace page-specific conventions with a small, reusable desktop component language.

Primary files:

- Split `dashboard/static/css/main.css` into `tokens.css`, `shell.css`, `components.css`, `pages.css`, and `utilities.css` or an equivalent documented structure.
- Add macros/partials under `dashboard/templates/components/`.
- Refactor `dashboard/static/js/main.js` into API, state, components, and page-controller modules.
- Migrate `base.html` and every page template.

Tasks:

1. Define semantic color, type, spacing, height, border, elevation, motion, and z-index tokens.
2. Document density targets and component anatomy.
3. Build shared page header, toolbar, form field, toggle, select, card, status, data view, state panel, dialog, toast, and pagination components.
4. Consolidate icon rendering and remove application-chrome emoji/symbol buttons.
5. Eliminate inline styles, inline handlers, and template-local component CSS.
6. Centralize request lifecycle, API envelopes, cancellation, retries, dirty forms, and feedback.
7. Reserve glass blur for shell/overlay elevation.

Acceptance criteria:

- All pages use the same header, toolbar, card, form, state, and action primitives.
- Zero inline `onclick` handlers and zero JS `style.cssText` component definitions.
- No direct `fetch()` outside the shared API client.
- New modules can render native-looking configuration/actions from documented contracts.
- Token/component documentation includes do/don’t examples.

Audit gate: screenshot diff and component inventory confirm no parallel implementations remain.

### Phase 3 — Build the desktop application shell

Goal: make navigation and context feel persistent, fast, and predictable.

Primary files:

- `dashboard/templates/base.html`
- `dashboard/templates/partials/guild_header.html`
- Manifest and web routes
- New shell/navigation controller
- `palette.js`, `realtime.js`, `shortcuts.js`

Tasks:

1. Render manifest navigation server-side at first paint; remove fallback/hydration divergence.
2. Add the compact guild context bar with breadcrumb, health, page actions, and palette shortcut.
3. Implement progressive same-origin navigation after page scripts are modular controllers.
4. Preserve focus, title, history, scroll, filters, and unsaved-state rules.
5. Upgrade command palette into scoped Navigate/Run sections.
6. Make realtime connection and reconnect state visible but quiet.
7. Add real shortcut-help dialog and route-specific shortcut registration.

Acceptance criteria:

- First paint and hydrated navigation are identical.
- Internal navigation updates the workspace without reloading shell assets and has a hard-navigation fallback.
- Back/forward restores the correct page, filters, tabs, scroll, and focus.
- Current guild/page/connection state is always visible.
- Palette results never leak from another guild.

Audit gate: keyboard-only run through every global destination and browser-history test.

### Phase 4 — Unify core moderation workflows

Goal: reduce clicks and context switching in the highest-frequency desktop work.

Primary files:

- `dashboard/templates/pages/guild.html`
- `members.html`, `member_detail.html`, `moderation.html`
- Moderation/member API routes and controllers

Tasks:

1. Convert guild overview loads into independent data sources with per-card states.
2. Build the unified Moderation workspace described in UX-04.
3. Preserve member search/filter/sort state in URL and session state.
4. Add member side inspector at desktop widths with full-page fallback.
5. Replace all quick-action variants with the shared action dialog.
6. Make moderation cases/warnings use names, linked targets, consistent timestamps, row details, and resilient pagination.
7. Update counters/rows incrementally from SSE with a visible last-updated state.

Acceptance criteria:

- A moderator can find and act on a member without losing list context.
- Warn/timeout/kick/ban have consistent validation, consequence text, permission preflight, progress, and result feedback.
- No destructive action is color-only or icon-only.
- Partial API failure does not blank healthy overview sections.
- Median click count for audited moderation tasks is reduced from baseline.

Audit gate: run task measurements with mouse and keyboard at every desktop viewport.

### Phase 5 — Give every module a native workspace

Goal: retain shared interaction rules while giving each module the tools its domain requires.

Tasks:

1. Introduce shared module workspace tabs/sections: Overview, Configure, Operate, Activity, Help.
2. Implement the Community, Logging, Moderation, Post, Roles, and Verification workspaces defined above.
3. Keep schema-driven forms for ordinary settings; use dedicated components only where the task warrants them.
4. Display module health and repair actions consistently at the top.
5. Standardize action outcomes, audit records, timestamps, channel/role/member selectors, and permission warnings.

Acceptance criteria:

- Every module uses the same shell, health, tabs, forms, dialogs, states, and feedback.
- No module requires raw Discord IDs or JSON when a safe resource picker/builder is possible.
- Empty, loading, permission-denied, deleted-resource, success, and error states exist for every module data view.
- A newly registered module inherits the standard workspace without custom CSS.

Audit gate: module-by-module contract, screenshot, keyboard, and failure-state review.

### Phase 6 — Accessibility, responsive desktop, motion, and performance convergence

Goal: remove remaining quality gaps after workflows stabilize.

Tasks:

1. Resolve A11Y-01 through A11Y-06.
2. Define responsive desktop behavior for 1024, 1280, 1440, 1920, and ultrawide layouts.
3. Ensure tables use controlled horizontal behavior or column prioritization rather than body overflow.
4. Verify 200% zoom and text resizing without hidden actions.
5. Keep motion 120–240ms, transform/opacity-first, and disabled under reduced motion.
6. Remove unnecessary blur, layout-triggering animation, and duplicate data loads.
7. Add performance marks for navigation, data-ready, and action completion.

Acceptance criteria:

- Zero axe critical/serious violations on all audited states.
- Every workflow is keyboard-complete with visible focus and logical order.
- WCAG AA contrast passes for text, controls, focus, and semantic states.
- No unintended horizontal page scrolling at audited viewports or 200% zoom.
- Reduced-motion mode removes decorative movement without removing status feedback.
- No long task or obvious interaction hitch in standard local profiling.

### Phase 7 — Final cohesion audit and release gate

Goal: prove Bark behaves like one application rather than six modules and several standalone pages.

Tasks:

1. Repeat the complete baseline audit from a clean authenticated session.
2. Review every route in normal, empty, loading, error, disabled, stale-resource, and permission-denied states.
3. Compare terminology, icon, title, action placement, form order, save behavior, timestamp, and status behavior across all modules.
4. Remove deprecated CSS/selectors/scripts only after exhaustive repository searches and browser coverage.
5. Update operator/user documentation and the module-author UI contract.
6. Resolve or explicitly defer every audit-register item with rationale.

Release criteria:

- All first-party pages pass tests, keyboard review, axe, and screenshot review.
- No broken links, dead actions, inconsistent enabled state, console errors, or failed network calls.
- No duplicate component implementations remain without a documented reason.
- All six modules pass the same health, settings, action, state, and permission contracts.
- The top audited workflows are faster or equal in clicks and demonstrably clearer.
- Production health is verified after restart; Python module changes are not considered deployed before restart.

## Mandatory iteration loop

Run this loop after every phase and after any substantial visual iteration:

1. **Inventory:** search all templates/modules for the pattern being replaced; do not sample only one module.
2. **Static checks:** Python compilation, JS syntax, template render, `git diff --check`, and project lint/type checks when configured.
3. **Tests:** focused unit/contract tests, then full `pytest`.
4. **Browser matrix:** all target desktop viewports, normal and reduced motion, 100% and 200% zoom.
5. **State matrix:** loading, populated, empty, validation error, server error, offline, permission denied, disabled module, and stale Discord resource.
6. **Interaction audit:** mouse, keyboard, command palette, history, focus restoration, unsaved changes, and destructive action confirmation.
7. **Visual audit:** hierarchy, alignment, density, truncation, icon consistency, semantic color, motion, overflow, and compositing.
8. **Integration audit:** compare UI state with API, database, module service, and mocked/live Discord result.
9. **Register:** add newly discovered issues, attach evidence, close verified items, and reprioritize remaining work.
10. **Repeat:** do not advance while P0/P1 regressions introduced by the phase remain open.

## Definition of desktop-quality completion

Bark is complete only when:

- Navigation, guild context, health, permissions, and page actions remain predictable across every screen.
- All module pages look and behave as members of one system.
- Every control has one meaning, one interaction model, and one feedback model.
- The interface reveals useful health and context before the operator has to search.
- Common moderation work retains context and minimizes page transitions.
- Status reflects authoritative bot behavior, not optimistic UI state.
- Every page has polished loading, empty, success, error, disabled, and repair states.
- Keyboard, focus, contrast, zoom, reduced motion, and desktop viewport behavior are release gates.
- New modules can adopt the same contracts without duplicating shell, form, dialog, state, or data-view code.

## Verification commands expected during implementation

```bash
source .venv/bin/activate
python -m compileall -q app.py bot dashboard database modules services tests
node --check dashboard/static/js/main.js
node --check dashboard/static/js/palette.js
node --check dashboard/static/js/realtime.js
node --check dashboard/static/js/shortcuts.js
pytest -q
git diff --check
```

Add Playwright/axe commands in Phase 0 and make them part of the standard verification path before Phase 1 begins.
