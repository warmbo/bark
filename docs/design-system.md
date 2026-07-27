# Design System

All visual tokens and layout primitives are defined in `dashboard/static/css/main.css` (~2200 lines, single stylesheet).

## CSS Custom Properties (Root)

### Base
| Token | Value | Usage |
|---|---|---|
| `--bg-base` | `#0a0a0d` | Page background |
| `--bg-elevated` | `#111114` | Secondary surfaces |
| `--bg-card` | `rgba(22,22,28,0.75)` | Card surface (glass) |
| `--bg-sidebar` | `rgba(10,10,13,0.95)` | Sidebar background |
| `--bg-hover` | `rgba(255,255,255,0.04)` | Hover state |
| `--bg-active` | `rgba(59,130,246,0.12)` | Active/selected state |

### Accent
| Token | Value |
|---|---|
| `--accent` | `#3b82f6` (blue) |
| `--accent-hover` | `#60a5fa` |

### Text
| Token | Value | Usage |
|---|---|---|
| `--text-primary` | `#ededef` | Headings, body |
| `--text-secondary` | `#a1a1aa` | Subtle text |
| `--text-tertiary` | `#71717a` | Placeholders, hints |

### Status
| Token | Value |
|---|---|
| `--green` | `#22c55e` |
| `--yellow` | `#eab308` |
| `--red` | `#ef4444` |
| `--orange` | `#f97316` |

### Glass
| Token | Value |
|---|---|
| `--glass-tint` | `rgba(255,255,255,0.03)` |
| `--glass-tint-strong` | `rgba(255,255,255,0.06)` |
| `--glass-border` | `rgba(255,255,255,0.06)` |
| `--glass-blur` | `blur(16px)` |
| `--glass-blur-heavy` | `blur(24px)` |

### Borders (low contrast, per user preference)
| Token | Value |
|---|---|
| `--border-subtle` | `rgba(255,255,255,0.04)` |
| `--border-card` | `rgba(255,255,255,0.05)` |
| `--border-input` | `rgba(255,255,255,0.07)` |
| `--border-hover` | `rgba(255,255,255,0.10)` |

### Radius (all 0px for sharp corners)
All `--radius-*` tokens are set to `0px`.

### Typography
| Token | Value |
|---|---|
| `--font-family` | `'Inter', -apple-system, system-ui, sans-serif` |
| `--font-size-body` | `16px` |
| `--font-size-caption` | `13px` |
| `--font-size-title` | `clamp(26px, 2.5vw, 34px)` |

### Spacing (clamp-based for responsive scale)
| Token | Value |
|---|---|
| `--space-xs` | `clamp(6px, 0.4vw, 10px)` |
| `--space-sm` | `clamp(8px, 0.6vw, 14px)` |
| `--space-md` | `clamp(12px, 1vw, 22px)` |
| `--space-lg` | `clamp(14px, 1.2vw, 24px)` |
| `--space-xl` | `clamp(20px, 2vw, 36px)` |

### Controls
| Token | Value |
|---|---|
| `--control-height` | `42px` |
| `--control-height-sm` | `34px` |

## Component Patterns

### Content Card
```html
<article class="content-card">
  <div class="card-header">
    <h2 class="card-title">Title</h2>
    <p class="card-description">Description</p>
  </div>
  <div class="config-body">Content</div>
</article>
```
- Background: `var(--bg-card)` with `backdrop-filter: var(--glass-blur)`
- Never nest cards without a distinct semantic boundary
- Actions go in `.card-header-actions` (right side of card header)

### State Panel
Used for empty, loading, error, and permission-denied states:
```html
<div class="state-panel state-empty"><span class="state-panel-icon">...</span>
  <div><strong>Title</strong><p>Message</p></div>
  <button type="button" class="btn btn-sm" data-refresh-section="...">Retry</button>
</div>
```
CSS classes: `.state-empty`, `.state-error`, `.state-loading`, `.state-permission`

### Tables
```html
<div class="table-scroll">
  <table class="data-table">
    <thead><tr><th>Col</th></tr></thead>
    <tbody><tr><td>Value</td></tr></tbody>
  </table>
</div>
```
- `width: 100%`, `border-collapse: collapse`
- Rows alternate subtle background for readability
- `.cell-truncate` for single-line text overflow
- `.table-actions` column for action buttons

### Forms
- `.form-grid` — auto-fit responsive grid (min 280px)
- `.form-grid-2` — 2 equal columns
- `.form-grid-3` — 3 equal columns (at >1600px)
- `.form-group` — label + input + hint + error wrapper
- `.form-label-row` — label + boolean toggle in one row
- `.form-actions` — button row at bottom
- `.form-actions-static` — button row without outer padding
- `.form-hint` — help text below input (`font-size: 13px`, `--text-tertiary`)
- `.field-error` — validation error (`--red` color)

### Module Workspace
- `.module-workspace` — root container for module detail pages
- `.module-workspace-header` — header with name, status, toggle, reload, role access
- `.module-health-strip` — 4-column metric row (Runtime, Configuration, Version, Commands)
- `.workspace-tabs` — tab bar with `role="tablist"`
- `.tab-panel` — each tab's content panel
- `.operation-grid` — grid of action cards in Operate tab
- `.action-card` — individual action form card
- `.action-result` — feedback area below action submit

### Danger Zone
```html
<article class="content-card danger-zone">
  <div class="card-header"><h2 class="card-title">Danger zone</h2><span class="status-badge status-danger">Admin only</span></div>
  <div class="danger-zone-list">
    <div class="danger-zone-row">
      <div><strong>Action name</strong><p>Description</p></div>
      <button class="btn btn-danger btn-sm">Execute</button>
    </div>
  </div>
</article>
```
- Only present in the tab that owns the affected data
- Each row names affected data, describes irreversibility, requires confirmation

### Dialogs (BarkDialog)
```html
<div class="dialog-overlay" id="app-dialog-overlay" aria-hidden="true" hidden>
  <div class="app-dialog" role="alertdialog" aria-modal="true" aria-labelledby="dialog-title">
    <div class="dialog-icon" aria-hidden="true">icon</div>
    <h2 id="dialog-title" data-dialog-title></h2>
    <p data-dialog-message></p>
    <div class="dialog-actions">
      <button type="button" class="btn" data-dialog-cancel>Cancel</button>
      <button type="button" class="btn btn-danger" data-dialog-confirm>Confirm</button>
    </div>
  </div>
</div>
```
- JavaScript API: `BarkDialog.confirm({title, message, confirmLabel, danger})` → `Promise<boolean>`
- Escape closes, backdrop click closes, focus trapped inside
- Only styled overlay dialogs — native `confirm()`, `prompt()`, `alert()` are prohibited

### Status Badge
```html
<span class="status-badge status-success"><span class="status-indicator"></span>Enabled</span>
```
Variants: `status-success` (green), `status-neutral` (gray), `status-danger` (red)

## Responsive Breakpoints
- Mobile: `480px` — stacked layouts, full-width controls
- Tablet: `768px` — 2-column grids begin
- Desktop: `1024px` — 3-column grids, sidebar visible
- Wide: `1600px+` — 5-column stats grid, expanded spacing

## Ambient Background
Two fixed-position `::before`/`::after` pseudo-elements on `body` create subtle blue ambient orbs:
```css
body::before { /* Orb 1 — top-right, #3b82f6, blur(120px) */ }
body::after { /* Orb 2 — bottom-left, #2563eb, blur(120px) */ }
```
Orbs drift slowly via `@keyframes orb-drift-1/2` (20s/25s cycles). No per-card shadow effects.

## View Transitions
```css
@view-transition { navigation: auto; }
::view-transition-old(root) { animation: 160ms ease-out both vt-fade-out; }
::view-transition-new(root) { animation: 200ms ease-out both vt-fade-in; }
```
Supported in Chrome/Edge 111+. Fallback: 220ms opacity fade via `.page-enter` keyframes.

## Page Level Classes
- `.page-container` — main content wrapper (fade-in animation)
- `.page-header-standard` — consistent page header structure
- `.page-eyebrow` — small label above title (`--text-secondary`, `13px`)
- `.page-title` — page heading (`--font-size-title`)
- `.page-subtitle` — page description
- `.page-actions` — action buttons area in header
