# Moderation Dashboard Workflows

Authoritative behavior for the moderation workspace. Layout rules are in `docs/module-workspace.md`; endpoint implementations are in `dashboard/routes/api/moderation.py`, `dashboard/routes/api/notes.py`, and `modules/moderation/module.py`.

## Feature map

| Workflow | UI/controller | API | Persistence | Permission |
|---|---|---|---|---|
| Cases | `module_tabs/moderation_cases.html`, `moderation-workspace.js` | `GET/DELETE moderation/cases` | `ModerationCase` | list: workspace access; delete: `moderation.cases.delete` |
| Warnings | `moderation_warnings.html` | `GET/DELETE moderation/warnings` | `Warning` | clear: `moderation.warnings.delete` |
| Notes | `moderation_notes.html` | `GET/POST/PATCH/DELETE notes` | `UserNote` | create/edit/delete: `moderation.notes.create` plus module role override |
| Rulesets/rules | `moderation_rulesets.html` | `rulesets` and nested `rules` CRUD | `RuleSet`, `Rule` | administrator/module access |
| Word lists | `moderation_wordlists.html` | `wordlists` CRUD | `WordList` | administrator/module access |
| Voice history | `moderation_voice.html` | `GET/DELETE moderation/voice-history` | `VoiceSession` | purge: `guild.manage` |
| Audit/attachment retention | Configure danger zone | `DELETE moderation/audit-logs`, `attachments` | `AuditLog`, `FileAttachment` | `guild.manage` |

All guild model predicates and constructors use canonical `str(guild_id)` values.

## Notes: complete edit/delete flow

1. The Notes tab loads `GET /api/v1/guilds/{guild_id}/notes` and renders escaped record content.
2. Add opens the populated form; Edit loads the selected record values and locks the member target.
3. Save validates client-side, disables itself, and calls POST or PATCH.
4. The server validates a numeric target ID and non-empty content no longer than 2,000 characters. It derives the author from the authenticated session, never trusts a browser-supplied `author_id`.
5. The API checks the moderation module role override and `moderation.notes.create` before each mutation.
6. Confirmed success closes the form, reloads notes, and shows a toast. Failure retains form contents and restores Save.
7. Delete names the note as permanent work, uses `BarkDialog.confirm`, disables the clicked control, calls DELETE, reloads data only after success, and restores the control on error.

## Case and warning deletion

A case DELETE is intentionally a soft deletion: it marks the case resolved and removes it from the active case list while retaining audit history. The confirmation states this result. A warning DELETE marks the warning inactive; its associated case remains available. Neither action reports success until the endpoint has committed.

## Rulesets and word lists

Rulesets and word lists load independently with skeleton, populated, empty, and error/Retry states. Inline editors preserve values until a confirmed API response. Rule saves validate regular expressions locally and require a matching word/domain list for list-backed triggers. All row deletes use the shared styled confirmation, including consequences for referenced word lists.

## Shared dialog and retries

`BarkDialog.confirm` in `dashboard/static/js/main.js` is the only destructive confirmation system. It has an alert-dialog role, handles Escape/Cancel, restores focus, resolves replaced dialogs safely, and is used by cases, warnings, notes, rulesets, rules, word lists, module destructive actions, and purges.

`moderation-workspace.js` is loaded only for the moderation module by `module_detail.html`. It owns every extra moderation tab and binds tab-click reloads plus Retry/Refresh actions. Do not move its data loaders into templates: template scripts run before base JavaScript utilities.

## Regression coverage

- `tests/test_dashboard/test_api.py`: note persistence, edit persistence, delete persistence, validation preserving stored text, module role access, cases/warnings route contracts.
- `tests/test_dashboard/test_frontend_a11y_contract.py`: workspace action contract, confirmation usage, conditional Operate tab, in-place module toggle, contextual danger-zone placement, tab semantics, and cache-version references.
- `tests/test_modules/`: ruleset/voice domain behavior.
