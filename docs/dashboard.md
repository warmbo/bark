# Dashboard UI and Control Contract

This document describes the maintained dashboard behavior. It is both an implementation reference and an audit checklist.

## Shared module workspace

All modules render through `dashboard/templates/pages/module_detail.html` and use:

1. **Header** — back link, module name/description, enabled status, enable toggle, reload action, and compact Role Access disclosure.
2. **Health strip** — runtime, configuration state, version, and command count.
3. **Tabs** — `Operate` only when executable actions exist, `Configure`, `About`, followed by meaningful module-specific tabs.
4. **Operate** — action cards generated from `get_actions()`; an empty Operations tab is prohibited.
5. **Configure** — schema fields and contextual module-level data-retention actions where applicable.
6. **About** — narrative, metadata, and registered commands.

`module-workspace.js` is the shared controller. It handles dirty tracking, Save/Discard, role access, toggle/reload loading states, action submission, destructive confirmation, and success/error feedback.

## Moderation tabs

| Tab | Read endpoint | Mutations | Empty state |
|---|---|---|---|
| Cases | `GET moderation/cases` and `GET moderation/cases/{number}` | `DELETE moderation/cases/{number}` | No active cases |
| Warnings | `GET moderation/warnings` | `DELETE moderation/warnings/{id}` | No active warnings |
| Notes | `GET notes` | `POST notes`, `PATCH/DELETE notes/{id}` | No notes yet |
| Rulesets | `GET rulesets` | Ruleset and nested rule CRUD | No rulesets configured |
| Word Lists | `GET wordlists` | Word-list CRUD | No word lists configured |
| Voice | `GET moderation/voice-history` | Admin purge of voice history | No voice history yet |

`dashboard/static/js/moderation-workspace.js` owns all six tabs. Each loader must render one of four states: skeleton loading, populated content, an explanatory empty panel, or an error panel with Retry. Tab activation and each Refresh control invoke the matching loader.

### Edit/delete rules

- Never use `window.confirm()` or `window.prompt()`.
- Destructive actions use `BarkDialog.confirm()` and state the scope and permanence.
- Buttons are disabled and marked `aria-busy` while a request is running.
- Success shows a toast and refreshes affected content.
- Failure shows an error toast and restores the control.
- Forms call `reportValidity()` and perform domain checks (for example regex compilation and required word-list selection) before sending data.
- Event delegation is used for dynamically rendered rows; do not attach listeners after each render.

### Danger zones

Danger zones are contextual: Voice contains voice-history deletion only; Moderation Configure contains audit-log and attachment-metadata retention actions. Each operation is server-scoped, requires a styled confirmation, and reports the deleted record count.

## Access behavior

Roles: `viewer`, `moderator`, `admin`, `owner`.

- Backend middleware and `check_api_permission()` are authoritative.
- Templates may hide controls that the current role cannot use, but hiding a control is never authorization.
- Permission-denied API responses are surfaced through `safeFetch()` error messages and toast/state feedback.
- Module access overrides are read/set/reset through `modules/{name}/role-access`.

### Per-server access (no view-only tier)

Each server's "Ready to manage" flag (owner, `ADMINISTRATOR`/`MANAGE_GUILD`
Discord permission, or an owner-configured staff role) drives what a user
sees:

- **Ready to manage** → the card is openable and shows the reason
  ("You own this server" / "You manage this server on Discord" / "You have
  this server's Admin role" / "You have this server's Moderator role").
  Full guild pages: overview, Members, Modules, Moderation, Settings, and
  the module workspace.
- **No manage access** → the card renders as a locked, non-openable
  `guild-card-readonly` card, and the middleware denies every `/guild/{id}`
  page and API route (403). There is no read-only view-only tier — a member
  who cannot manage the server is locked out entirely.

Running the Bark instance grants nothing per-server: the instance owner is
treated like any other member unless they own the server, hold Discord
manage permissions on it, or hold a configured staff role there.

See `docs/permissions-model.md` for the full rule set (moderator role
snapshotting, Dashboard Access card, admin-role display).

## Mobile navigation drawer

Below 769px the sidebar becomes an off-canvas drawer (`initMobileDrawer()`
in `main.js`): the hamburger (top-left) opens it; the drawer X, scrim tap,
Escape, a left-swipe, or picking a nav item close it; a right-swipe from
the left edge opens it. The closed drawer is `inert` + `aria-hidden`, the
toggle reflects `aria-expanded`, and opening focuses the drawer. On
desktop the sidebar is unchanged.

## Layout and spacing

Use spacing tokens (`--space-xs` through `--space-xl`) and shared surfaces:

- `.content-card` for a bounded content unit;
- `.card-header` and `.card-header-actions` for titles and local controls;
- `.config-body` for form content;
- `.form-actions` at the bottom of forms;
- `.state-panel` for loading-resolution empty/error messaging;
- `.table-scroll` around data tables;
- `.operation-grid`, `.form-grid-2`, and `.form-grid-3` for responsive groups.

Keep actions adjacent to the content they affect. Cards should not contain unexplained blank space. Wide tables scroll within their card. Drawers and dialogs must have labels, focusable controls, Escape dismissal, and a backdrop/Cancel path.

## Frontend utilities

`dashboard/static/js/main.js` provides:

- `safeFetch(url, options)` — timeout, request cancellation, JSON parsing, HTTP error normalization;
- `escHtml(value)` — safe interpolation into generated markup;
- `showToast(message, type)` — transient status/alert feedback;
- `showSkeleton(container, count, type)` — loading placeholders;
- `loadApiSelect(select)` / `initApiSelects()` — Discord API-backed selects;
- `BarkDialog.confirm(options)` — accessible styled confirmation;
- shared tab and sidebar behavior.

Generated user or API content must pass through `escHtml()`. After inserting Lucide placeholders, call `lucide.createIcons()`.

## Regression checklist

Before deployment:

- [ ] Module list toggles have labels, loading state, rollback, and toast feedback.
- [ ] Toggle, reload, all workspace tabs, Save, Discard, role Save/Reset, and every Operate submit work.
- [ ] Cases view/delete and pagination work.
- [ ] Warnings clear works.
- [ ] Notes create/edit/delete work.
- [ ] Rulesets create/rename/toggle/delete and rule create/edit/delete work.
- [ ] Word lists create/edit/delete work.
- [ ] Voice and all three purge actions work.
- [ ] Empty, loading, error/Retry, success, and permission-denied paths are visible.
- [ ] No browser-native prompt/confirm calls exist.
- [ ] `node --check` passes for changed scripts.
- [ ] `python -m pytest -v --tb=short` passes.
- [ ] The service restarts and reaches an active/healthy state.
