# Bark — UI/UX & Discord Functionality Audit

**Focus:** User experience, workflow efficiency, visual polish, Discord feature completeness

---

## 1. Dashboard (Server Selection)

### 1.1 Hardcoded client_id in invite link
`dashboard.html:34` — the invite URL contains a hardcoded bot client ID `1401694499142500414`. For self-hosted instances, this links to the original ZENHAWX bot, not the user's own instance. The invite link should be configurable or hidden when the user's own bot can't receive invites.

**Fix:** Make the invite URL configurable via `config.yaml` or env var (`BARK_INVITE_URL`). If unset, show a generic "Configure your bot at the Discord Developer Portal" message with a link.

### 1.2 No connection retry or status indicator
The dashboard page shows "No Servers Connected" immediately if the bot isn't connected. There's no polling or retry mechanism to detect when the bot comes online. An admin who just invited the bot would need to refresh manually.

### 1.3 No bot status on dashboard page
The base template sidebar shows a "Connected" status dot, but on the server selection page, there's no indication whether the bot is actually connected to Discord or just running without a token. A disconnected bot still shows "Connected" because the status dot is static HTML.

---

## 2. Guild Overview Page

### 2.1 "Boosting" stat label is misleading
`guild.html:13` shows `{premium_subscription_count} boosting` — but this is displayed as a `stat-change` under the Members stat, not as its own stat. This is confusing — it looks like the "boosting" is a trend indicator when it's actually a count.

### 2.2 Activity feed lacks interactivity
The feed shows the last 8 moderation cases but: no way to click into a case, no way to load more, no auto-refresh, no filtering. Once loaded, it's static forever.

### 2.3 No actionable insights
The overview shows member count, channels, roles, and boost tier, but doesn't tell the admin anything useful like: "Your server grew by X members this week" or "Moderation cases are up 50% this week" or "Your most active channel is #general". The intelligence API has this data but the overview doesn't use it.

### 2.4 No quick-action for common tasks
The Quick Actions section has: Members, Cases, Modules, Announce. Missing: "Invite Members" (with a vanity URL or invite link generator), "View Audit Log", "View Online Members".

---

## 3. Members Page

### 3.1 Hard limit of 200 members
`members.html:70` fetches `limit: 200`. For servers with 500+ members, this silently truncates the member list. Worse, the count text says "{total} members" but only the first 200 are shown, creating a false sense of completion.

### 3.2 Quick action popovers lack clear cancel
The popover appears on click and dismisses only on outside click or after executing the action. There's no visible "X" or "Cancel" button inside the popover after opening.

### 3.3 Role filter only populated once
The role dropdown is populated on page load via the `/roles` endpoint but never refreshed. If a role is created/deleted while the page is open, the filter list becomes stale.

### 3.4 No "jump to member" by ID
For support tickets or reports, admins often have a Discord user ID. There's no way to paste an ID and jump directly to that member.

### 3.5 Member cards don't show join date
The card shows account age (days old) but not join date. For growth analysis, both are useful.

---

## 4. Moderation Page

### 4.1 Warning table shows raw user IDs
`moderation.html:175` renders `<code>{{ user_id }}</code>` — raw Discord IDs with no username resolution. For moderation, admins need to see who the person is, not a 19-digit number.

**Fix:** Enrich warnings with usernames from the guild member cache, or show a link to `/guild/{id}/members/{user_id}`.

### 4.2 Notes form has no user lookup
The "Add Note" form requires pasting a numeric Discord user ID. There's no member search/autocomplete. Admins have to open a separate browser tab to find the user ID.

**Fix:** Replace the User ID text input with an `api_select` populating from `/guilds/{id}/members`.

### 4.3 No case detail view
Cases are shown in a flat table. Clicking a case doesn't open details — there's no way to see: full case description, related attachments, appeal status, or edit the reason. The API supports GET `/cases/{case_number}` but the frontend never uses it.

### 4.4 Voice History lacks useful context
Shows `user_id` (numeric ID), channel name, timestamps. No username, no duration formatting (just raw seconds), no link to the member's detail page. `duration_seconds` shows as raw seconds (e.g. "3600s") instead of "1h 0m".

### 4.5 No bulk moderation
No way to select multiple members and perform actions on all of them. Common use case: kick 10 spambots at once.

### 4.6 No search across cases
The cases table has pagination but no text search. Admins who want to find "all cases where reason contains 'spam'" have to flip through pages.

---

## 5. Module Pages

### 5.1 Module toggle has no loading state
`modules.html:21-26` — toggling a module sends an API call but the toggle switches instantly. If the API fails, it reverts. This looks snappy but the user has no feedback that a request is in-flight. A 500ms delay is imperceptible but a 3-second timeout with no spinner is confusing.

### 5.2 Module cards show "puzzle" icon for everything
`modules.html:18` — every module card shows the same generic `puzzle` icon. Modules should define their own icons in the registration and have them rendered here.

### 5.3 Config forms don't show saved state
After saving module config, the save bar disappears and a toast confirms, but there's no visible "last saved" timestamp. If the admin makes another change, they can't tell if the previous save already took effect.

### 5.4 No config draft persistence
The save bar tracks unsaved changes but doesn't persist drafts. If the admin navigates away (or loses their session), config changes are lost.

**Fix:** Use `persistForm()` pattern from the JS utilities to save drafts to localStorage.

### 5.5 Action forms don't validate required fields
The markdown editor's toolbar buttons and form fields have `required` attributes, but the form is submitted via JS and validation is manual. A field with `required` won't trigger browser-native validation because the form uses JS submission.

---

## 6. Settings Page

### 6.1 Command prefix is hardcoded
`settings.html:53` shows the command prefix as `!` but this value is never loaded from the server. The `/settings` API endpoint returns saved settings, but the form always shows `!`.

### 6.2 Mod/Admin role IDs are text inputs
`settings.html:57-64` — role IDs require pasting a numeric ID. Should be dropdowns populated from Discord roles with search. This is a major UX friction point for new admins.

### 6.3 No "Discord Server Settings" section
Discord server settings (verification level, explicit content filter, default notification settings, etc.) are shown on the guild overview page in the "Server Info" card but are read-only. No way to change them from Bark.

### 6.4 Config health check is hidden
The config health section is collapsed at the bottom of the Modules card. For first-time admins, this should be more prominent.

---

## 7. Module Detail Page

### 7.1 Module-specific "Actions" don't show loading indicators
The action form buttons disable during submission but there's no spinner or indication of progress beyond disabled text.

### 7.2 "Back to Modules" link is easy to miss
The back link is small and positioned above the page title, not visually grouped with any other navigation element.

### 7.3 No module enable/disable toggle on the detail page
The module detail page shows enabled/disabled status but has no toggle. The user has to go back to the Modules list to toggle. The module header has a reload button but no enable/disable toggle.

### 7.4 About stories are long blocks of text
The "About" section for each module shows stories as lengthy paragraph descriptions. These should be collapsible or formatted with bullet points for scannability.

---

## 8. Visual & CSS Polish

### 8.1 Skeleton loaders are static
`main.css` defines skeleton classes but they have no animation. The skeletons appear as solid gray blocks with no shimmer/pulse effect. This makes pages feel stuck rather than loading.

**Fix:** Add a shimmer animation:
```css
.skeleton {
    background: linear-gradient(90deg, var(--bg-elevated) 25%, var(--bg-card) 50%, var(--bg-elevated) 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
    border-radius: var(--radius-sm);
}
@keyframes shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
}
```

### 8.2 No `prefers-reduced-motion` support
The CSS has transitions and animations (sidebar, save bar, toasts) but no `@media (prefers-reduced-motion)` block. Users with vestibular disorders may experience discomfort.

### 8.3 Table rows don't alternate colors
Data tables (cases, warnings, voice history) have no alternating row colors. On long tables, it's hard to visually track across columns.

### 8.4 No responsive breakpoints below 768px
The CSS appears to have no mobile-optimized breakpoints. On phone screens, the sidebar occupies 240px of the viewport, leaving almost no room for content.

### 8.5 Toast notifications not accessible
`showToast()` appends a toast to `<body>` but doesn't use `aria-live="polite"` for screen readers. Users relying on assistive technology won't hear success/error notifications.

### 8.6 Inline styles in JS templates
`member_detail.html` has multiple inline styles in the JS template strings:
- `style="vertical-align:middle;margin-right:4px"` on icon SVGs — should be a CSS class
- `style="color:var(--green/red)"` on result spans — should be CSS classes (`.action-success`, `.action-error`)

---

## 9. Discord Feature Gaps

### 9.1 Ticket System — database exists, no module
`database/models/tickets.py` defines `Ticket` and `TicketMessage` models. The `ticket_created` event is in the RealtimeBridge event map. But no module implements the ticket system. This is a standard feature for community servers.

### 9.2 Join/Leave Logging is split between community and logging
Welcome/goodbye messages live in the community module's settings schema and event handlers. But file uploads and voice state logging are in the logging module. An admin looking for "member join logging" doesn't know where to look.

### 9.3 No audit log viewer
`GET /api/v1/audit-log` exists and returns Discord audit log entries. But there's no page in the dashboard to view them. The only way to see audit logs is via the API.

### 9.4 No invite management UI
Invite tracking data is collected but there's no dashboard page showing invite codes, usage, or who invited whom. The `/invite-stats` slash command works in Discord but the dashboard has no equivalent.

### 9.5 No analytics/insights dashboard
The intelligence API returns structured data (member growth, activity trends, moderation counts) but there's no chart rendering on the frontend. The guild overview shows raw numbers but no trend visualization.

### 9.6 No role management UI from dashboard
Roles can be created via slash commands (`/auto-role`, `/conditional-role`, `/role-menu`) but the dashboard has no page for role management. Admins who prefer GUI over slash commands can't manage roles.

### 9.7 No permission calculator/visualizer
There's no way for an admin to see: "Which members have the Manage Server permission?" or "What permissions does @Moderator have?" — standard features in Discord management bots.

### 9.8 No emoji/sticker management
The `/assets` endpoint returns emoji and sticker inventory but there's no page to view them. Emoji names and images are collected but never displayed in the dashboard.

---

## 10. Command Palette & Navigation

### 10.1 No keyboard shortcut to close palette with Escape
The palette supports Escape to close, but the overlay background click also closes. This is fine.

### 10.2 No "recent pages" in empty palette
When the palette opens with no search query, it shows the first 8 items from the manifest. These are always the same items regardless of what the user was doing. No recency or frequency sorting.

### 10.3 No Ctrl+K shortcut on the server selection page
Ctrl+K only works inside a guild context (where the manifest is available). On `/dashboard`, there's no palette but the keyboard shortcut is silent — no feedback to the user that the palette isn't available here.

---

## 11. Loading State Gaps

| Page | Loading State | Empty State | Error State | Status |
|------|:---:|:---:|:---:|:---:|
| Guild overview | ✅ Skeleton HTML | ✅ "No recent activity" | ✅ Error fallback | Complete |
| Members | ✅ Skeleton | ✅ "No members match" | ✅ Error fallback | Complete |
| Member detail | ✅ Skeleton | ✅ Various empty messages | ✅ Retry button | Complete |
| Moderation cases | ✅ Skeleton | ✅ "No cases yet" | ✅ "Failed to load" | Complete |
| Moderation warnings | ✅ Skeleton | ✅ "No active warnings" | ✅ "Failed to load" | Complete |
| Moderation notes | ✅ Skeleton | ✅ "No notes yet" | ✅ "Failed to load" | Complete |
| Voice history | ✅ Skeleton | ✅ "No voice history" | ✅ "Failed to load" | Complete |
| Modules list | ✅ (server-side rendered) | ✅ "No modules" | ❌ No error state | Partial |
| Module detail | ✅ (server-side rendered) | ✅ "No settings" | ❌ No error state | Partial |
| Settings | ✅ (server-side rendered) | N/A | ❌ Config health section handles errors | Partial |
| Dashboard | ❌ No loading transition | ✅ "No Servers" | ❌ No bot-disconnected state | Partial |

---

## 12. Priority Improvement Roadmap

### P0 — Quick Wins (under 30 minutes each)

1. **Add skeleton shimmer animation** — CSS only, transforms loading states from "stuck" to "in progress"
2. **Add `prefers-reduced-motion`** — CSS only, accessibility essential
3. **Replace user IDs with member links in warnings/voice tables** — template change, links to `/members/{id}`
4. **Add alternating row colors to data tables** — CSS only
5. **Format voice duration as "1h 30m" instead of raw seconds** — JS helper function
6. **Make the invite URL configurable** — env var or config.yaml

### P1 — High Value (1-2 hours each)

7. **Add role selectors (not text inputs) for mod/admin role IDs** — replace `<input>` with `<select>` populated from guild roles API
8. **Add member search to the notes form** — replace User ID text input with `api_select` from `/members` endpoint
9. **Add case detail view** — modal or expanded row with full case info, links, and resolution
10. **Add charts to guild overview** — lightweight chart rendering from intelligence API data (member growth, moderation trends)
11. **Create invite management page** — list invites, show usage stats, revoke invites

### P2 — Feature Completion (2-4 hours each)

12. **Implement ticket system module** — database model exists, needs module with dashboard and Discord commands
13. **Create audit log viewer page** — fetch from `/audit-log`, display with filtering and category grouping
14. **Add role management dashboard page** — CRUD for auto-roles, conditional roles, role menus
15. **Create emoji/sticker browser** — show guild emojis and stickers in a visual grid
16. **Add bulk moderation** — multi-select member cards with batch warn/kick/ban

### P3 — Polish & Long-Term

17. **Responsive breakpoints below 768px** — mobile-friendly sidebar collapse and content reflow
18. **Draft persistence for config forms** — localStorage-backed form state
19. **Config validation inline feedback** — show field-level errors after save attempt
20. **`aria-live="polite"` on toasts** — screen reader support
21. **Add "last saved" timestamp after config save**
22. **Module icons in module list** — each module defines its own icon

---

## Summary: Key UX Metrics

| Metric | Current State | Target |
|--------|:---:|:---:|
| Loading states with animation | ❌ Static skeletons | ✅ Shimmer animation |
| Error states on all pages | ⚠️ 7/11 pages | ✅ 11/11 pages |
| Empty states on all pages | ✅ 11/11 pages | ✅ 11/11 pages |
| Keyboard navigation | ✅ Partial (palette + tabs) | ✅ Full (all interactive elements) |
| Screen reader support | ⚠️ Skip link, ARIA labels, no toast announcements | ✅ Full ARIA support |
| Responsive < 768px | ❌ No mobile layout | ✅ Collapsed sidebar + stacked content |
| Config forms with draft persistence | ❌ Not saved | ✅ localStorage-backed |
| Member search usability | ⚠️ Manual ID entry | ✅ Autocomplete member selectors |
| Discord features surfaced in UI | ⚠️ 60% (modules exist but no UI) | ✅ 90%+ |
