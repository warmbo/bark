# Module Workspace Contract

Authoritative layout and interaction contract for every Bark module dashboard.

## Purpose and lifecycle

A module subclasses `modules.base.BarkModule`, exposes its schema/actions/tabs, and is rendered by `dashboard/routes/web/modules.py` through `dashboard/templates/pages/module_detail.html`. The generic controller is `dashboard/static/js/module-workspace.js`.

The module manager owns module discovery, enable/disable lifecycle, event registration, and module API route registration. Per-guild persisted state is `ModuleConfig`; per-module dashboard minimum-role overrides are `ModuleRoleAccess`.

## Required layout

| Element | Requirement | Implementation |
|---|---|---|
| Header | Required | Name, description, enabled status, enable toggle, reload, role-access summary/editor. |
| Health strip | Required | Runtime, configuration state, version, and command count. |
| Navigation | Required | Only tabs with a user workflow. Native tabs support arrows, Home, End, and selected state. |
| Operate tab | Conditional | Render only when `module.get_actions()` returns executable actions. Never render an empty Operations placeholder. |
| Configure tab | Required | Schema-backed fields, dirty tracking, Save/Discard, validation, and retained input on failure. |
| About tab | Required | Module lifecycle metadata and supported commands. |
| Extra tabs | Conditional | Register only distinct feature workflows via `get_extra_tabs()`. |
| Danger zone | Conditional | Put destructive controls in the tab that owns the affected data. |

The header must wrap on narrow viewports; it must not rely on horizontal overflow. Role Access remains in the compact header disclosure, adjacent to module status and lifecycle controls, rather than consuming a standalone panel.

## State and action contract

All retained controls follow the same sequence:

`control → handler → safeFetch → authorized API route → service/database/Discord action → confirmed response → in-place UI update`

- `safeFetch` provides timeout, HTTP normalization, and session-expiry behavior.
- Buttons disable and set `aria-busy` while requests run. A failure restores the control and leaves user input intact.
- Forms use browser validity plus endpoint validation. Save is disabled until values differ from the loaded baseline.
- Destructive actions call `BarkDialog.confirm`; the dialog identifies scope and permanence. Browser `alert`, `confirm`, and `prompt` are prohibited.
- Success is shown only after the API response; a toast and targeted data reload update visible state.
- Toggle state changes update the header status, health strip, and sidebar manifest in place. A full-page reload is prohibited.
- Loading, empty, error-with-Retry, permission-denied, saving, and success states use shared state panels, controls, and toast feedback.

## Form and spacing rules

Use `main.css` tokens (`--space-xs` through `--space-xl`) and the existing primitives:

- `.content-card` only for a bounded content unit; do not nest cards without a distinct semantic boundary.
- `.card-header` / `.card-header-actions` place local actions beside the title they affect.
- `.config-body`, `.form-grid`, `.form-actions`, and `.form-actions-static` organize forms.
- `.table-scroll` wraps wide tables; mobile uses stacked header/action rows rather than overflowing controls.
- `.state-panel` is mandatory for empty, failure, and retry states.

## Contextual danger zones

A danger zone lists only actions that affect the current tab's subject:

- Cases: individual case resolution/delete controls belong to the row being affected.
- Warnings: warning clear belongs to the warning row.
- Rulesets and word lists: deletion belongs to the relevant editor/list row.
- Voice: clears voice-session history only.
- Moderation Configure: clears moderation-wide audit and attachment metadata, which have no dedicated data-management tab.

Every row names the affected data, describes reversibility, requires confirmation, prevents duplicate submission, reports failure, and refreshes the owned view.

## Accessibility

Tabs have `role=tab`, `aria-controls`, `aria-selected`, and keyboard navigation. Controls have visible labels or programmatic names. The shared confirmation overlay is a modal alert dialog with focus restoration, Escape cancellation, and focus trapping. Dynamic content escapes server values and reruns Lucide rendering after insertion.

## Exceptions

Modules with no actions have no Operate tab. This is intentional and is not a missing feature. Module-specific extra tabs are permitted only where a complete backend workflow exists.
