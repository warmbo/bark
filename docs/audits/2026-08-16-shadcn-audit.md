# Bark v0.3.0 — shadcn/ui Visual System Conversion: Audit

Branch: `bark3` (created from `dev` @ `329c512`). Date: 2026-08-16.

Goal (per Cody): utilize `ui.shadcn.com` for the entire visual system, convert
everything existing to use it, and **self-host a pinned copy of shadcn locally so
the version can't change and break the site.**

---

## 1. Current frontend architecture (what we're converting FROM)

Bark's dashboard is a **server-rendered FastAPI + Jinja2** app. There is **no
Node.js, no npm, no Tailwind, no build/bundle step** — a hard architectural fact
that drives everything below.

| Area | Inventory |
|---|---|
| Static serving | `dashboard/static` mounted via `StaticFiles` (`setup_app.py:29`). No pipeline. |
| Templates | 33 `.html` Jinja2 templates (`templates/pages/*`, `templates/components/*`, `templates/module_tabs/*`) |
| Stylesheet | Single `dashboard/static/css/main.css`, **3483 lines, 539 distinct class selectors** |
| JS | 17 files, **3811 lines**, vanilla JS, loaded via plain `<script>` tags. Behaviors: `BarkDialog`, command palette, toasts, tabs, sidebar collapse, dropdown/popovers, per-module workspaces, realtime, dependency-free SVG charts |
| Icons | **lucide v1.22.0 from `unpkg.com` CDN** (external — a drift/availability risk) |
| Fonts | **Inter + JetBrains Mono from `fonts.googleapis.com` CDN** (external) |
| Existing design tokens | Documented in `docs/design-system.md`, defined as CSS custom properties in `main.css`: dark glassmorphism, `--accent #3b82f6`, sharp `0px` corners, Inter type |
| Existing macros | `templates/components/primitives.html` + `icons.html` — a nascent Jinja2 component system (foundation to extend) |
| Frontend contract tests | `test_css_contract.py`, `test_frontend_a11y_contract.py`, `test_frontend_js_contract.py`, `test_frontend_forms.py` — lock current classes/structure; **must be migrated alongside the redesign** |

### Component inventory (from 539 CSS classes → the primitives to convert)

- **Layout:** `.app-shell`, `.sidebar`, `.main-content`, `.context-bar`, `.content-container`, `.page-container`, `.settings-grid`
- **Card system:** `.content-card`, `.card-header`, `.card-title`, `.card-description`, `.card-header-actions`, `.config-body`
- **Controls:** `.btn` (+ `.btn-primary/.btn-danger/.btn-sm/.btn-xs/.btn-block`), `.form-input`, `.form-select`, `.form-textarea`, `.form-grid*`, `.form-group`, `.form-label`, `.form-hint`, `.toggle-switch`, `.checkbox-role-dropdown`
- **Feedback:** `.state-panel` (empty/error/loading/permission), `.status-badge`, `.toast`, `.skeleton*`, `.update-terminal`
- **Interactive:** `.tabs`/`.tab-panel`, `.palette*` (command palette), `.app-dialog`/`.dialog-overlay` (BarkDialog), `.hover-card`, `.role-access-popover`, `.workspace-drawer`
- **Data:** `.data-table`, `.table-scroll`, `.member-table`, `.pagination`, `.module-health-strip`
- **Layout components:** `.guild-card`, `.module-card`, `.dashboard-widget`, `.action-card`, `.danger-zone`, `.info-row`, `.event-item`

### External-dependency drift risk (the exact failure the user wants to prevent)

- `lucide` icons resolve to `https://unpkg.com/lucide@1.22.0` — the version is
  pinned today, but it's a third-party CDN outside our control (availability + the
  `@1.22.0` range could be re-resolved).
- Google Fonts stylesheet + `preconnect` resolve to Google — same availability/
  privacy consideration.
- shadcn/ui's whole value prop is "copy the source in and own it" — which is exactly
  the self-hosting model the user is asking for.

---

## 2. The core constraint: shadcn/ui is React, Bark is Jinja2

shadcn/ui components are **React components** built on **Radix primitives** (or
Base UI in the 2026 `cli v4`), styled with **Tailwind CSS v4 + CSS design tokens**.
Bark renders HTML server-side with vanilla JS. So "use shadcn for the entire visual
system" has two viable implementations:

- **Path A — Adopt shadcn's design system, keep server rendering.** Bring in
  Tailwind v4 + shadcn's design-token layer + shadcn's component *styles*, all
  **vendored and pinned locally**, and reimplement the components as Jinja2 macros
  (`{% macro button, card, dialog, badge, tabs, ... %}`) with small vanilla-JS
  behavior shims mirroring Radix. Preserves FastAPI/Jinja2 architecture and the
  existing deployment. This is the realistic, low-risk path for a self-hosted app.
- **Path B — Full React/Next.js rewrite** using real shadcn React components.
  Massive effort, replaces the rendering stack and deployment model (needs a Node
  build + separate frontend), much higher risk.

### How "self-host shadcn locally so the version can't change" works

shadcn already has an official **component registry** model
(`ui.shadcn.com/docs/registry`): a `registry.json` + per-item JSON served over HTTP,
which the `shadcn` CLI resolves. Two layers of pinning:

1. **Vendor the source.** After one initial install, the component source, the
   Tailwind v4 stylesheet, the design tokens, and the shadcn CSS are committed to
   the repo and owned locally. No live `npx shadcn add` against the remote registry
   after the pin; upgrades happen deliberately, reviewed, on our schedule.
2. **Pin the registry + deps.** Record the exact shadcn/ui version, Tailwind v4
   version, and dependency versions in a lockfile/manifest so nothing auto-resolves.
   Also move `lucide` + Google Fonts off their CDNs into local assets (same
   self-hosting rationale).

> **Decision needed from Cody:** Path A (recommended) vs Path B. Everything in the
> plan downstream (build tooling, deployment, timeline) depends on this choice.

---

## 3. What a conversion touches (size estimate, Path A)

1. **Add a frontend build/render path** for Tailwind v4 + shadcn tokens + component
   CSS (vendored Tailwind standalone CLI or a tiny npm build producing a single
   committed CSS output — decided in the plan).
2. **Tokens:** replace the hand-rolled `main.css` token block with shadcn's
   `@theme` design tokens (background, foreground, card, primary, secondary, muted,
   accent, destructive, border, input, ring, radius), mapped onto Bark's existing
   dark palette so the look is deliberately shadcn but on-brand.
3. **Primitives as Jinja2 macros:** build out `primitives.html` (and new
   `ui/*.html` macro files) covering button, card, badge, input, select, textarea,
   label, toggle/switch, tabs, dialog, dropdown, tooltip, popover, command
   (palette), table, skeleton, toast, separator, avatar, breadcrumb — emitting
   shadcn-utility-class markup.
4. **Convert all 33 templates** onto the macro layer; remove dead/duplicate CSS.
5. **JS behavior shims:** rewrite `BarkDialog`, palette, tabs, dropdowns, toasts as
   tiny headless-behavior shims matching Radix semantics (focus trap, aria, Esc
   close, keyboard nav) without React.
6. **Migrate the 4 frontend contract tests** to assert against the new class/token
   contract instead of the old `main.css` classes.
7. **Self-host assets:** vendor lucide icons (local sprite/module) + Inter/JetBrains
   Mono fonts locally; drop the two CDNs.
8. **Deployment:** confirm CT1109 can produce the build output (or commit the
   generated CSS as a build artifact so the deploy stays a plain `StaticFiles`
   mount — preferred, zero new runtime deps).

---

## 4. Risks / guardrails

- **Visual-regression contract:** the a11y + CSS + JS contract tests are the safety
  net; convert them in lockstep, don't leave them red on the old contract.
- **No-React honesty:** shadcn *React components* can't be dropped into Jinja2. Path
  A delivers shadcn's **visual system** (which is what "entire visual system"
  means) via the token + style layer, not the React source. If Cody truly needs the
  React components themselves, that forces Path B.
- **Pin discipline:** the whole point is "the version can't change and ruin our
  site" — so: commit generated assets, lock versions, never auto-pull.
- **Deployment unchanged** (uvicorn + StaticFiles) if we commit build artifacts —
  avoids touching the production service layout.

---

## 5. Bark-specific behavior preservation matrix

The rebuild is not accepted merely because every route renders. Each workflow
below has stable IDs, endpoint contracts, permission states, loading/empty/error
states, keyboard behavior, and realtime updates that must remain operational.
The v0.3 implementation deliberately changes presentation while retaining these
behavior contracts.

| Surface | Existing behavior that must survive | v0.3 visual/component mapping | Verification |
|---|---|---|---|
| Landing + OAuth | Public hero, authenticated redirect, Discord login, invite/setup CTAs, live version | Bark-image hero, shadcn buttons/cards/badges; no app shell | anonymous/auth route tests; desktop/mobile screenshot |
| Setup wizard | Token/client configuration, validation errors, secrets handling, first-run transition | card/form/alert/progress primitives | setup API tests; invalid/valid walkthrough |
| Guild selector | Online/offline guild cards, permission-aware access, stale Discord state, invite action | card/avatar/badge/dropdown/skeleton/empty | owner/admin/viewer/offline fixtures |
| Slug entry | `/g/{slug}` canonical redirect and not-found handling | unchanged routing; slug shown in server settings | redirect + collision tests |
| App shell | Responsive sidebar, collapsible groups/add-ons, guild context, command palette, breadcrumbs, logout | shadcn sidebar/command/collapsible/avatar | keyboard, mobile drawer, persistence, console |
| Dashboard | Aggregate stats, server-at-a-glance, recent activity, module status, skeleton/error/empty states | card/description-list/table/skeleton/alert | aggregate API, SSE refresh, zero-data fixture |
| Modules | Available/enabled state, add-on distinction, toggle, role access, owner restrictions, search | cards/switch/badge/popover/alert-dialog | manager/viewer/owner tests; reload and failure |
| Module detail | Generated config fields, dirty state, save/reset, enable/test/reload, channel/role selectors | field/switch/select/tabs/alert/dialog | every manifest field kind + validation errors |
| Announcements | Channel selection, message/embed composition, color/image/upload, Discord preview, send | tabs/field/popover/card/alert-dialog/toast | preview parity; upload/delete; no live send without permission |
| Auto Voice | Template/channel config, temporary-channel lifecycle, controls | tabs/card/select/field/table/dialog | workspace JS/API contracts and lifecycle tests |
| Logging | Event toggles, channel mapping, logs, filters, pagination/detail | switch/select/table/badge/sheet | filter/pagination/SSE; large log content |
| Moderation | Cases, warnings, notes, rulesets, wordlists, voice history; warn/timeout/kick/ban/unban/VC actions | tabs/table/dialog/alert-dialog/textarea/badge | permission matrix; destructive confirmations; pagination |
| Reputation | Leaderboard, thanks history, tiers, points and role rewards | tabs/table/progress/badge/dialog | empty/large datasets; tier CRUD and rank refresh |
| Role manager | Rules and assignments, role selectors, execution/result feedback | tabs/table/select/dialog/toast | rule CRUD; hierarchy/API failures |
| Speak | Text/channel/voice options, generation/playback status | form/select/progress/alert | workspace contract; unavailable voice/provider |
| Members | Search/filter/sort/pagination, avatar fallback, member detail, notes, role and moderation history | input/table/avatar/badge/pagination/sheet | keyboard search; special names; missing avatar |
| Statistics | Date windows, SVG charts, tooltips, responsive chart grids, public/private boundaries | cards/tabs/chart tokens/tooltip | chart JS contracts; no moderation leakage |
| Settings — Server | General identity, server URL slug, command/logging/automod settings, config health | sections/cards/fields/selects/alerts | save/validation/collision and health tests |
| Settings — Instance | backups, update channel/terminal, diagnostics, bot customization, hosted access/invites | owner-only cards/dialog/progress/table | owner-only API and hidden-UI tests; stream terminal |
| Plugin catalog | catalog browsing, availability, install/config state, source links | cards/badge/button/alert | disabled/unavailable/catalog-error states |
| Realtime | EventSource reconnect/backoff, activity refresh, cross-tab behavior | presentation-only change | disconnect/reconnect JS contract and browser console |
| Global feedback | BarkDialog promise API, toasts, focus restoration, image fallbacks, reduced motion | dialog/alert-dialog/toast/avatar/skeleton | Esc/tab/backdrop/aria-live/reduced-motion tests |

### Immutable behavior hooks

During migration, the following are API rather than styling details and cannot be
renamed opportunistically: endpoint paths and payloads; form field names; element
IDs read by JavaScript; `data-*` hooks; manifest field names; role/permission gates;
SSE event names; `BarkDialog` return semantics; `safeFetch` error/timeout behavior;
and CSS state classes toggled by the workspaces. New Jinja macros wrap these hooks
instead of replacing them. This permits a complete visual rebuild without a risky
simultaneous backend rewrite.

---

## 6. Backup, restore, and v0.2 compatibility audit

### Artifact inventory

| Artifact | Existing behavior | v0.3 compatibility requirement |
|---|---|---|
| SQLite `.db` | WAL-consistent owner backup creation and download existed; no upload/restore path | integrity-check upload; verify Bark schema; checksum; stage outside live DB; atomic startup swap; preserve current DB as rollback; run ordered migrations |
| Settings `.json` | Per-guild `bark-backup` format v1 exports guild settings, enabled module state, and module configs | continue accepting wrapper `{backup: …}` and bare payload; strict guild scoping; tolerate absent fields; reject foreign/future format safely |
| `.env` / environment | Runtime secrets and instance configuration; intentionally not in downloadable backups | never import from browser, never serialize tokens/client secrets, preserve in place across update |
| `config.yaml` / legacy config | optional deployment configuration outside the DB | do not overwrite automatically; document manual translation where environment overrides apply |
| uploads/media | Guild-scoped files on disk, not represented by settings JSON | preserve data directory during code update; treat archive/media migration as a separate explicit operation |
| add-on/plugin files | Code/config outside core database | preserve directories during update; re-discover against v0.3 manifest; never execute code from a DB upload |

### Required `.db` restore transaction

1. Accept only an owner-authenticated multipart `.db` upload with a bounded size.
2. Write to a temporary file; verify the SQLite header, `PRAGMA integrity_check`,
   and Bark identity (`guilds` table at minimum). Do not inspect or swap the live
   connection during the request.
3. Copy to `data/restore/restore-pending.db`, validate the copied bytes again, and
   atomically write a marker containing SHA-256, source name, size, tables, and time.
4. On the next process start, before SQLAlchemy opens the database, verify marker +
   checksum, create a WAL-consistent snapshot of the current live DB, remove stale
   WAL/SHM sidecars, and atomically replace the live DB.
5. Run the normal ordered idempotent migrations so v0.2 schemas receive all columns,
   indexes, plugin provenance, invites/access, slug, update, and newer module tables.
6. If validation fails, leave the live DB untouched and return a useful error. Keep
   the pre-restore snapshot as the explicit rollback artifact.

### Compatibility fixtures / acceptance

- A minimal historical Bark DB migrates from a pre-migration `guilds` schema.
- A real v0.2-shaped fixture retains guild IDs, module configs, cases, notes,
  warnings, reputation, role rules, instance access, and audit rows after migration.
- A current v0.3 DB round-trips without data loss.
- Corrupt SQLite, arbitrary SQLite, oversized files, checksum mismatch, and
  non-owner requests are rejected before the live database changes.
- Existing v1 JSON fixtures import both as a bare backup and wrapper object; unknown
  module names are reported rather than crashing the whole import.
- Database backups never contain `.env`, Discord token, OAuth secret, session key,
  or source/plugin code.

---

## 7. Rebuild implementation and release gates

1. **Pin:** exact Tailwind/Lucide/font versions and lockfile; committed CSS/fonts/icon
   bundle; no runtime CDN or npm access.
2. **Theme:** shadcn semantic tokens mapped to black/navy surfaces, electric-blue
   primary/ring colors, `0px` radius, Inter/JetBrains Mono, and subtle bundled Bark
   imagery. Stock white/rounded shadcn defaults are explicitly forbidden.
3. **Compatibility layer:** map existing selectors to tokens first so every page
   changes coherently while hooks remain stable; then move repeated markup behind
   Jinja primitives without rewriting route logic.
4. **Every state:** normal, hover, focus-visible, disabled, loading, empty, offline,
   permission denied, validation error, API error, success, destructive confirmation,
   and mobile overflow are part of the conversion.
5. **Release:** frontend contracts + full pytest + Ruff; independent review; render
   all templates; browser desktop/mobile/keyboard/console checks; pre-deploy DB
   backup; dev deploy; explicit visual sign-off; stable promotion; live health,
   login, settings, module, backup, and rollback checks.

The architecture intentionally favors behavior preservation over a React rewrite:
the application is rebuilt visually around locally-owned shadcn recipes while its
mature FastAPI/Jinja2/API/module contracts remain intact.
