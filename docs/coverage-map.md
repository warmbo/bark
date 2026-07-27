# Documentation Coverage Map

This map links maintained Bark features to their implementation and verification. Update it when adding, moving, or deleting a feature.

| Feature | Authoritative documentation | UI/controller | Routes/services | Models/Discord/background | Tests |
|---|---|---|---|---|---|
| App startup and composition | `README.md`, `docs/dashboard.md` | `app.py`, `dashboard/__init__.py` | `dashboard/app.py`, `services/bark_context.py` | `bot/client.py`, `services/module_manager.py` | `tests/test_config.py`, dashboard API/auth tests |
| Authentication and role access | `README.md`, `docs/dashboard.md` | `dashboard/routes/auth.py`, header session controls | `services/security.py`, `services/response.py` | `DashboardUser`, `DashboardGuildAccess`, `ModuleRoleAccess` | `tests/test_dashboard/test_auth_access.py`, `test_api.py` |
| Module lifecycle/workspace | `docs/module-workspace.md` | `module_detail.html`, `module-workspace.js`, `primitives.html`, `main.css` | `dashboard/routes/web/modules.py`, `routes/api/modules.py` | `BarkModule`, `ModuleConfig`, module manager | `test_frontend_a11y_contract.py`, `test_api.py` |
| Sidebar/manifest navigation | `docs/dashboard.md` | `base.html`, `main.js`, `palette.js` | `routes/api/manifest.py` | module page registrations | frontend contract/API tests |
| Moderation cases and warnings | `docs/moderation-workflows.md` | cases/warnings templates, `moderation-workspace.js` | `routes/api/moderation.py`, `moderation_service.py` | `ModerationCase`, `Warning`, moderation commands | `test_api.py`, moderation service/module tests |
| Moderation notes | `docs/moderation-workflows.md#notes` | `moderation_notes.html`, `moderation-workspace.js` | `routes/api/notes.py` | `UserNote` | `test_note_edit_and_delete_persist`, `test_note_validation_preserves_existing_record` |
| AutoMod rulesets and word lists | `docs/moderation-workflows.md`, `docs/moderation-tab-architecture.md` | ruleset/wordlist templates, `moderation-workspace.js` | `ModerationModule.get_api_routes()`, `ruleset_engine.py` | `RuleSet`, `Rule`, `WordList`, message listener | module and frontend contract tests |
| Voice history and retention | `docs/moderation-workflows.md`, `docs/module-workspace.md#contextual-danger-zones` | `moderation_voice.html`, Configure danger zone | `routes/api/moderation.py` | `VoiceSession`, `AuditLog`, `FileAttachment`, voice-state listener | `test_modules/test_moderation_voice.py`, frontend contract tests |
| Logging module | `modules/logging/README.md` | generic module workspace | logging module API routes | `LogConfig`, logging listeners | dashboard/module tests |
| Welcome module | `modules/welcome/README.md` | generic module workspace | module config API | `ModuleConfig`, member join/remove listeners | module tests |
| Shared dialogs/forms/states | `docs/module-workspace.md` | `base.html`, `primitives.html`, `main.js`, `forms.js` | standard response helpers | n/a | `test_frontend_a11y_contract.py`, `test_frontend_forms.py` |
| Database and migration runtime | `README.md`, `database/migrations/__init__.py` | n/a | `database/engine.py` | `database/models/*` | `tests/test_database/*` |
| Realtime updates | `docs/dashboard.md` | `realtime.js` | `routes/api/realtime.py`, `services/realtime_bridge.py` | event bus | dashboard API tests |
| Deployment and configuration | `README.md`, `bark.service` | settings page | `config.py`, health route | systemd, Discord, SQLite | `tests/test_config.py` |

## Source-reference policy

Important source files contain short repository-relative doc pointers rather than duplicated prose:

- Module workspace template and controller → `docs/module-workspace.md`
- Moderation workspace controller and Notes API → `docs/moderation-workflows.md`
- Specialized module docs → their module README

New public routes, background jobs, persistent models, and module entry points must be added to this map with a matching test location.
