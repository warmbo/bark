# Bark — UI Standard

The visual + interaction conventions every page and component should obey. Derived from the 2026-08-18 audit. **Note:** the existing `docs/design-system.md` is **stale** — it lists pre-contrast/glass-pass token values. The values below are the currently-shipped tokens (verified against `dashboard/static/css/main.css` and the contrast/glass passes).

## Tokens (root, in `main.css`)

### Surfaces (dark, glass — final approved 2026-08-04 pass)
| Token | Value | Note |
|---|---|---|
| `--bg-base` | `#14141a` | Raised out of near-black for contrast |
| `--bg-card` | `rgba(35,35,45,0.62)` | Glass card, more transparent after the glass pass |
| `--bg-card-hover` | `0.68` | |
| `--bg-input` | `rgba(40,40,52,0.70)` | |
| `--bg-sidebar` | `rgba(18,18,24,0.68)` | |
| `--bg-surface` | `rgba(28,28,36,0.66)` | |
| `--bg-elevated` | `#111114` → brightened | Secondary surfaces |

### Text (all pass WCAG AA on base AND card)
| Token | Value | Contrast |
|---|---|---|
| `--text-primary` | `#ffffff` | 18:1 |
| `--text-secondary` | `#d6d6dd` | 12:1 |
| `--text-tertiary` | `#a8a8b3` | ≥7:1 |

### Borders / glass
| Token | Value |
|---|---|
| `--border-subtle` | 0.08 alpha |
| `--border-card` | 0.10 alpha |
| `--border-input` | 0.15 alpha |
| `--border-hover` | 0.2 alpha |

### Accent + status
`--accent: #3b82f6`, `--accent-hover: #60a5fa`; `--green/#22c55e`, `--yellow/#eab308`, `--red/#ef4444`, `--orange/#f97316`.
**Known issue (queued P5):** white text on `--accent` (3.9:1) and `--red` (3.8:1) fails AA for 13-14px button labels.

### Radius — ALL `0px` (sharp corners, user preference)
### Typography — `Inter` system stack; body 16px; caption 13px; title `clamp(26px,2.5vw,34px)`
### Spacing — `--space-xs..xl` clamp-based (audit flagged these produce odd non-scale values 17/21/33px — queued in migration)

## Component conventions

| Component | Canonical markup / rule |
|---|---|
| **Button** | Single `.btn` system (visible WITHOUT hover — bg elevated + text primary). Variants: `.btn-primary`, `.btn-danger`, `.btn-sm`, `.btn-xs`. |
| **Content card** | `<article class="content-card"><div class="card-header"><h2 class="card-title">…` |
| **State panel** | `.state-panel` + `.state-empty/.state-error/.state-loading/.state-permission` with a Retry button |
| **Table** | `.data-table` in `.table-scroll`; `<caption>` + `<th scope="col">` (a11y contract) |
| **Dialog** | `BarkDialog.confirm/pick` only — native `confirm/alert/prompt` **banned**; Escape/backdrop/focus-trap |
| **Status badge** | `.status-badge.status-success/.status-neutral/.status-danger` + `.status-indicator` |
| **Danger zone** | `.danger-zone` card, admin-only, per-row confirm |
| **Page header** | `.page-header-standard` → SHOULD use the `page_header` macro (currently under-used — queued P4) |
| **Forms** | `.form-grid`/`-2`/`-3`, `.form-group`, `.form-hint`, `.field-error`; every control needs a `name` (contract-enforced) |
| **Icons** | Lucide via `{{ icon("name", size) }}`; re-render with `refreshIcons()` after any `innerHTML` swap |

## Responsive breakpoints
Mobile `480px` · Tablet `768px` · Desktop `1024px` · Wide `1600px+`. Responsive derives from layout rules, not emergency media-query hacks.

## A11y (contract-enforced)
- Keyboard navigation works end-to-end (focus visible, logical tab order).
- No nested interactive elements; no native confirm/alert/prompt.
- Live regions (`aria-live`) on auto-updating stat blocks.
- Every form control named/labelled; SR table semantics (caption + scope).
- Buttons visible without hover; contrast AA on body text.

## Terminology
**One vocabulary, verified consistent:** "Server" (user-facing) — no visible "Guild(s)" in copy. **Server** = the Discord server being managed; **Instance** = the Bark deployment itself (settings split General→Server + Instance is the correct model).

## Migration note
The in-flight shadcn REMAKER (branch `feat/shadcn-migration`, sources in `bark3-v030/frontend/src`) will flatten glass into shadcn surfaces, add tokens for shadows, and consolidate the spacing scale. Until it lands, the above tokens are the live standard. Do not edit generated `main.css` directly on that branch — edit `frontend/src/{legacy,v3,theme}.css` and rebuild.
