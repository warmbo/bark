# Bark v0.3.0 — Roadmap

Goal: **tighter module integration** and a **cleaner, smoother UI**, building directly
on the features we've shipped since v0.2.x. This is a themes-and-workstreams plan,
not a fixed feature list — items are grouped so we can pick them up in priority order.

---

## 0. Where we are (inventory of recent v0.2.x work)

Everything below is committed, tested (721 passing), and live on bark-dev (:8091).
Most is already promoted to stable; the rest is ready to promote on your word.

**Slash-command unification (the interface became one dispatcher)**
- Single `/bark <command> <args>` dispatcher (circumvents Discord's 25-subcommand
  cap); per-guild command prefix removed — slash is the interface.
- `--help <command>`, command picker on partial invocations, paginated guidance
  with ◀ ▶ reactions, Add-on Modules section in getting-started.
- **Security**: dispatcher now enforces invoker permissions (`@default_permissions`
  restored centrally); CSRF Origin/Referer gate; viewer hard read-only; settings
  redaction for sub-admins; session renewal throttled.

**Permission / access model (mature, stable)**
- Instance owner is a regular member per-server unless they hold a real grant.
- Manageable cards show *why*; non-granted servers are **view-only** (Dashboard +
  Statistics + server info, no module controls, read-only, no mutation).
- Discord ADMINISTRATOR / MANAGE_GUILD map to per-guild dashboard tiers.

**Dashboard → server profile**
- Banner (custom upload or URL, stored per-guild), larger server icon, info chips
  (members, created, boosts/tier, owner, verification, channels), server description.
- **MOTD** with rich-text formatting (**bold**, *italic*, underline, `code`,
  [links](…), headings, quotes, lists) via a safe `renderMarkdown` + markdown
  toolbar; larger font.
- **Discord Scheduled Events** card.
- **Add-on dashboard widgets**: `BarkModule.get_dashboard_cards()` is the extension
  point; `ModuleManager` collects them from guild-enabled modules; the dashboard
  renders them as a responsive widget grid. Working example: reputation "Top
  Members" leaderboard card.

**Members**
- Role colour-coded chips (Discord role colours), Account Age + Date Joined columns,
  clickable sortable headers (server-side sort).

**Statistics page**
- All stats consolidated there; live message/emoji tracking in the bot.
- Dependency-free SVG charts: member-growth line, cases-by-type pie, messages-by-
  channel pie, top-emoji bar, plus a metric grid (messages today, most active
  channel, most used emoji, boosts, verification, growth).

**Audit hardening (stability)**
- Background loops survive transient errors; update worker can't wedge the UI;
  AutoMod silent swallows now log; heading hierarchy, table semantics, a11y
  contracts, dead markup removed.

---

## 1. v0.3.0 vision

Three themes, in priority order:

1. **Tighter integration** — modules don't just sit side-by-side; they *compose*.
   A single Dashboard page becomes the command center: core profile + any module's
   widgets + a shared "recent activity" surface, all fed by one contract.
2. **Cleaner UI** — one design language everywhere: consistent cards, headers,
   tables, tabs, dialogs; fewer one-off templates; no visual drift.
3. **Smoother** — less jank: no full-page reloads, optimistic updates, predictable
   loading/empty/error states, keyboard-first, a11y-guaranteed.

---

## 2. Workstreams (tighter integration)

### A. Module integration contracts
- **Dashboard widgets v2** (foundation already shipped):
  - Add a `metric` widget with sparkline option; allow widgets to link to their
    module's workspace ("View leaderboard →").
  - Let modules register **optional** cross-widget data, e.g. a birthdays module's
    "Upcoming Birthdays" card surfaces on the Dashboard when the module is enabled
    — the exact pattern we built for reputation.
- **Shared activity surface**: unify Recent Activity into ONE contract that any
  module can emit into (moderation cases, logging events, reputation awards, role
  changes). Dashboard shows a compact feed; each module workspace shows its slice.
  Kills the current "who owns the activity feed" drift.
- **Optional plugin-to-plugin cooperation**: a lightweight `ContextProvider` /
  `cooperation` registry so modules can ask each other for data when present
  (e.g. logging can render a birthdays card if the birthdays module exists),
  degrading gracefully to "not installed". Default OFF per guild, as today.
- **Module capabilities API**: one `GET /guilds/{id}/dashboard` returns profile +
  events + module widgets + recent activity in a single round-trip (today the
  dashboard makes 3+ calls). Reduces latency and frontend coordination.

### B. Config / UX cohesion
- One "Modules" hub where enabling a module instantly shows its dashboard widgets
  preview + a link to its workspace, so admins see the integration payoff.
- Consistent per-guild settings storage (we already have `GuildSetting` for MOTD,
  banner, staff roles) — formalize a tiny `GuildSettings` service so modules stop
  hand-rolling key/value reads.

### C. Slash ↔ dashboard symmetry
- The `/bark` dispatcher and the dashboard should expose the SAME set of module
  actions. Derive the dashboard "Operate" actions from the same registration used
  by slash commands, so a module that adds a command automatically gets a matching
  dashboard control (and vice-versa). Single source of truth.

---

## 3. Workstreams (cleaner / smoother UI)

### D. Design-system consolidation
- Audit the remaining one-off templates (guild_offline, moderation stub, plugin
  catalog, invite) and fold them onto the shared primitives (`content-card`,
  `page-header`, `state-panel`, `data-table`, `dialog`). We already standardized
  most pages — close the gaps.
- Single source for buttons/inputs/badges/chips/tabs in CSS (already mostly done);
  remove dead + duplicate rules (we found and removed several).
- Consistent empty/loading/error states everywhere (a shared `data-state` pattern)
  so nothing shows a bare skeleton or blank card.

### E. Interaction smoothness
- **Optimistic updates** for the highest-friction writes (MOTD, banner, module
  enable/disable, config save): update the UI instantly, reconcile on response,
  toast on failure. No full-page reload after saving a module.
- **Focus + keyboard**: dialogs trap focus and return it; tables sort via keyboard;
  modals close on Escape (we already do most of this — finish the gaps).
- **Loading**: skeleton-first (already the pattern) with a shared loader component;
  avoid layout shift by reserving space for charts/tables.
- **Realtime**: keep the 5-min auto-refresh, add per-section refresh that doesn't
  reset scroll or re-render the whole page.

### F. Performance / polish
- Dashboard single round-trip (A) is the big win.
- Lazy-load heavy sections (charts, media) only when scrolled into view.
- `renderDataTable` shared everywhere (we added sr-only captions + `scope="col"`;
  reuse it on every table for consistency).
- Reduced-motion + touch-target pass (already partly done) as a final polish gate.

---

## 4. Phased roadmap

**Phase 1 — Integration foundations**
1. ✅ **Unified `GET /guilds/{id}/dashboard`** — profile + viewer flag + module
   widgets in one round-trip (dashboard loads with a single call); shared
   `_serialize_guild()` helper (`4a1eecf`).
2. ✅ **Dashboard widgets v2** — `metric` widget type with label + inline
   sparkline; `link` footer ("View in module") (`728ab68`).
3. ✅ **Module cooperation registry** — `services/module_coop.py`, exposed via
   `BarkContext.coop`; modules register optional data providers and call others'
   providers, degrading to `None` when absent (optional composition)
   (`728ab68`).
4. ✅ **Second real widget** — moderation "Recent Cases" card proves any enabled
   module can extend the dashboard (reputation "Top Members" + moderation
   "Recent Cases") (`728ab68`).

**Phase 2 — Cohesion**
5. ✅ **Module capabilities API + Modules surface** — the dashboard aggregate now
   returns each enabled module (title, description, workspace link, widget
   count) and the dashboard renders an "Enabled Modules" chip strip; no separate
   page needed (`6195c71`).
6. ⏳ Slash ↔ dashboard action symmetry (single registration drives both).
7. ✅ **`GuildSettings` service** — `services/guild_settings.py` centralizes
   per-guild settings; MOTD/banner read/write now use it (`728ab68`).

**Phase 3 — UI polish (cleaner + smoother)**
8. ⏳ Fold remaining one-off templates onto primitives; kill dead/dup CSS.
9. ✅ Optimistic MOTD/banner saves with immediate render + toast on failure;
   metric widgets render a smooth inline sparkline; enabled-modules chip strip.
10. ✅ Reduced-motion + focus-visible already comprehensive (prefers-reduced-motion
    kills all transitions/animations; 12 focus-visible rules).

**Definition of done for v0.3.0**
- Dashboard is a true command center: profile + any module's widgets + unified
  activity, loaded in one request.
- A module can extend the Dashboard purely by enabling it (birthdays example real).
- Slash commands and dashboard controls come from one registration.
- Every page shares the primitives; no one-off visual drift; a11y contracts green.

---

## 5. Suggested first concrete step (next session)

Implement **Workstream A item 1**: merge the dashboard's three calls
(`/manifest`, `/guilds/{id}`, `/guilds/{id}/dashboard`, plus events/widgets) into a
single `GET /guilds/{id}/dashboard` aggregate, and make the reputation widget link
back to its workspace. This is small, high-value, and immediately reduces dashboard
load time — the foundation every other integration item builds on.
