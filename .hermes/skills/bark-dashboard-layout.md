---
name: bark-dashboard-layout
description: Layout, spacing, and grouping improvements for Bark's dashboard module pages and sidebar.
---

# Bark Dashboard Layout & Grouping Improvements

## When to use
Use this pattern when cleaning up page density and section grouping in Bark's dashboard UI.
Covers sidebar nav cleanup, module page arrangement, and spacing consistency across module pages.

## Scope
- `dashboard/templates/pages/module_detail.html`
- `dashboard/templates/pages/modules.html`
- `dashboard/templates/pages/settings.html`
- `dashboard/templates/pages/members.html`
- `dashboard/templates/pages/moderation.html`
- `dashboard/static/css/main.css`

## Principles
- Group related controls with explicit section wrappers, not just spacing.
- Keep sidebar minimal; move command palette/search to extensions if ever needed.
- Use cards only when there is visible grouping benefit; overlapping cards waste space.
- Preserve JS behavior; do not break dependent selectors.

## Template changes
- Replace indiscriminate `.detail-grid` with `.module-section` wrappers.
- Put page `active_page` context into route handlers; do not depend on `request` path checks.
- Use grouped header rows for module status + actions + version pills.
- Use control rows in member/browsing views; avoid stacked single filters.

## CSS changes
- Reduce `.page-container` padding to `20px 24px`.
- Tighten `.content-card`, `.card-header`, `.module-card`, `.stat-card` padding and margins.
- Tighten `.form-group` spacing and section labels.
- Compact `.member-controls`, `.filter-row`, `.table-header` spacing.
- Keep existing mobile breakpoints; do not increase empty margins on mid-width.

## Pitfalls
- Do not remove `active_page` updates in backend route handlers.
- Do not drop JS selectors while restructuring templates.
- Do not crash CSS with malformed values; watch for injection artifacts.

## Bug reference
- Mod `loadNotes()` assumed `raw.notes` was always iterable. Guard array inputs with `Array.isArray()`.
