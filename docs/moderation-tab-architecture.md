# Moderation Page Tab Architecture

## Overview

The moderation module workspace (at `/guild/{id}/modules/moderation`) has **6 extra tabs** registered by `ModerationModule.get_extra_tabs()` in `modules/moderation/module.py`:

| Tab ID | Label | Template | API Endpoint |
|--------|-------|----------|-------------|
| `cases` | Cases | `module_tabs/moderation_cases.html` | `GET /guilds/{id}/moderation/cases` |
| `warnings` | Warnings | `module_tabs/moderation_warnings.html` | `GET /guilds/{id}/moderation/warnings` |
| `notes` | Notes | `module_tabs/moderation_notes.html` | `GET /guilds/{id}/notes` |
| `rulesets` | Rulesets | `module_tabs/moderation_rulesets.html` | `GET /guilds/{id}/rulesets` |
| `wordlists` | Word Lists | `module_tabs/moderation_wordlists.html` | `GET /guilds/{id}/wordlists` |
| `voice` | Voice | `module_tabs/moderation_voice.html` | `GET /guilds/{id}/moderation/voice-history` |

Each tab template contains ONLY HTML markup with a skeleton/shimmer placeholder div:
```html
<div id="mod-cases-content" aria-live="polite"><div class="skeleton skeleton-card"></div></div>
```

The data loading is handled by a SEPARATE JS file, NOT by inline scripts in the templates.

## Data Loading Architecture

### JS Files (loaded order matters)

1. **`base.html`** — always loads these:
   - `main.js?v=17` — core utilities: `safeFetch`, `escHtml`, `showToast`, `showSkeleton`, `initTabs`
   - `forms.js` — `BarkForms` and `BarkDialog` namespaces

2. **`module_detail.html`** — appends these in `{% block scripts %}`:
   - `module-workspace.js?v=4` — config form, in-place toggle, reload, role access, action forms
   - **`moderation-workspace.js?v=3`** — data loading for all 6 extra tabs (cases, warnings, notes, rulesets, word lists, voice)

**Order is critical:** `main.js` defines `safeFetch`, `showSkeleton`, `escHtml`, `showToast`. `moderation-workspace.js` calls all of these. If `moderation-workspace.js` loads before `main.js`, every function reference throws `ReferenceError`.

### How moderation-workspace.js Works

The file (`dashboard/static/js/moderation-workspace.js`, ~382 lines) is a single IIFE:

1. **Guard clause** (line 3-4): Checks for `document.querySelector('.module-workspace[data-module-name="moderation"]')`. If the current page isn't a moderation module workspace, the IIFE returns silently. This prevents the script from activating on other modules' pages.

2. **Loader functions** — one per tab:
   - `loadCases(page)` — fetches cases, renders data-table with pagination controls
   - `loadWarnings()` — fetches active warnings, renders data-table
   - `loadRulesets()` — fetches rulesets + wordlists, renders ruleset cards with toggle/rename/add-rule/delete buttons
   - `loadWordlists()` — fetches wordlists, renders data-table with inline editors
   - `loadVoice()` — fetches voice sessions, renders data-table
   - `loadNotes()` — fetches member notes and supports create, edit, and delete

3. **Loader map** (line 363):
   ```javascript
   const loaders = {cases: loadCases, warnings: loadWarnings, notes: loadNotes,
                    rulesets: loadRulesets, wordlists: loadWordlists, voice: loadVoice};
   ```

4. **Event delegation** — uses `document.addEventListener('click', ...)` with `event.target.closest()` to handle all button clicks. This avoids needing per-button bindings and survives DOM replacement (since the listeners live on `document`, not on elements that get replaced by `innerHTML`).

5. **Tab click binding** (line 376):
   ```javascript
   Object.entries(loaders).forEach(([name, loader]) =>
     byId(`workspace-tab-${name}`)?.addEventListener('click', loader));
   ```

6. **Immediate load** (line 381):
   ```javascript
   Object.values(loaders).forEach(loader => loader());
   ```
   **CRITICAL:** This calls ALL loader functions immediately on page load, not just the active tab. This is intentional — the skeleton/shimmer placeholder in each tab panel gets replaced immediately with real data (or an empty/error state) regardless of whether the tab is visible. Each loader:
   - Shows skeleton: `loading(container)` → calls `showSkeleton(container, 2, 'card')`
   - Fetches API data
   - On success: replaces innerHTML with table/cards
   - On error: shows error state with retry button
   - On empty: shows empty state message

### Refresh buttons

Each tab template has a "Refresh" button with `data-refresh-section="cases"` (or warnings/rulesets/etc.). The click handler at line 366:
```javascript
if (target.dataset.refreshSection) loaders[target.dataset.refreshSection]?.();
```
This reloads data for that specific section. It does NOT affect other sections.

## Root Causes of "Shimmer Forever"

### ROOT CAUSE 1: Missing script include (HISTORIC)
`moderation-workspace.js` was **not loaded anywhere**. The `module_detail.html` only included `module-workspace.js` in its `{% block scripts %}`. The data-loading JS file existed on disk but was never referenced by any template. This was the recurring bug:

1. Refactor moved moderation data views from inline scripts in `moderation_data.html` to separate tab templates + external JS file
2. The external JS file (`moderation-workspace.js`) was created but NOT added to any template's script inclusion
3. Every subsequent edit touched the templates or the JS file but never fixed the missing include
4. Each time someone rebuilt the page from scratch, they'd write shiny new templates with skeleton placeholders but forget the script include again

**Fix:** Add `<script src="/static/js/moderation-workspace.js?v=1"></script>` to `module_detail.html`'s `{% block scripts %}`.

### ROOT CAUSE 2: Script load order dependency
If `moderation-workspace.js` loads before `main.js`, `safeFetch`, `showSkeleton`, `escHtml`, etc. are undefined → the IIFE throws `ReferenceError` on the first call → `loaders` is never built → no loaders fire → skeleton stays forever.

### ROOT CAUSE 3: Inline JS syntax error (old pattern)
Before the `moderation-workspace.js` approach, `moderation_data.html` had inline `<script>` blocks. A single syntax error (`(`, `)` or `{` mismatch) prevented the entire IIFE from running. The browser's JS parser never executed `loadCasesMod()` etc., so skeleton placeholders stayed forever. The `moderation_data.html` page is now unused (orphaned).

**Diagnosis when shimmer shows forever:**
1. Open browser DevTools Console
2. Look for: `ReferenceError: safeFetch is not defined` → script load order problem
3. Look for: `<script>` tag for `moderation-workspace.js` in the HTML source → missing include
4. Look for: `SyntaxError` → syntax error in the JS file or inline script

### ROOT CAUSE 4: JINJA2 `{% include %}` and JS context in tabs
When tab templates are `{% include %}`d in `module_detail.html`, any inline `<script>` blocks execute during page render, BEFORE `main.js` loads at the bottom of `base.html`. The old inline scripts called `safeFetch` before it was defined. The new approach avoids this entirely by putting all logic in `moderation-workspace.js` which loads via `{% block scripts %}` (after `main.js`).

## Tab Registration

Tabs are registered in `modules/moderation/module.py:get_extra_tabs()`. Each tab has:
- `id` — unique ID, used for `workspace-tab-{id}` button ID, `tab-{id}` panel ID
- `label` — visible tab label
- `template` — Jinja2 template path (included via `{% include %}`)

The templates live in `dashboard/templates/module_tabs/moderation_*.html`.

## What NOT To Do

1. **NEVER remove the `moderation-workspace.js` include from `module_detail.html`**. If you refactor tab templates, ensure the script include stays.
2. **NEVER add inline `<script>` blocks to tab templates** that call `safeFetch` or other `main.js` utilities. The templates are included BEFORE `main.js` loads. Put ALL data-fetching logic in `moderation-workspace.js`.
3. **ALWAYS bump `?v=N`** when changing `moderation-workspace.js`, `module-workspace.js`, or `main.js`.
4. **NEVER move `moderation-workspace.js` to a different directory** without updating the script tag path.
5. **NEVER remove the notes tab** without removing its loader and CRUD controls together; its backend is the standalone `notes.py` API because notes are member data.

## Testing the Fix

1. Restart the service: `systemctl --user restart bark`
2. Navigate to a guild workspace: `/guild/{id}/modules/moderation`
3. Verify each tab replaces the skeleton placeholder with real data within ~1 second
4. Click each tab to verify reload
5. Click each Refresh button to verify section-specific reload
6. Open DevTools Console — check for no JS errors
