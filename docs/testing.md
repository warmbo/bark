# Testing

## Running Tests

```bash
cd /home/cody/Projects/bark
pytest           # All tests
pytest -v        # Verbose output
pytest -x        # Stop on first failure
pytest -k "note" # Run tests matching "note"
pytest --coverage  # With coverage report (if pytest-cov installed)
```

SQLite (aiosqlite) is used for tests — no external database needed. The test environment is isolated via `tests/conftest.py` which monkeypatches all config values to use a `tmp_path` database.

## Test Structure

```
tests/
├── conftest.py                          # Global fixtures: setup_test_env, db
├── test_dashboard/
│   ├── test_api.py                      # API endpoint tests (httpx)
│   └── test_frontend_a11y_contract.py   # AST-based template/CSS contract tests
└── test_services/
    └── test_realtime_bridge.py          # EventBus → RealtimeBridge integration
```

## Test Files

### `tests/conftest.py`

Global fixtures applied to every test:

| Fixture | Scope | Purpose |
|---|---|---|
| `setup_test_env` (autouse) | function | Sets env vars (`BARK_DATABASE_URL`, `BARK_BOT_TOKEN`, etc.), updates config singleton, resets database engine singleton |
| `db` | function | Initializes DB tables via `init_db()`, yields, tears down via `close_db()` |

### `tests/test_dashboard/test_api.py`

API endpoint tests using `httpx.AsyncClient` against the FastAPI app with a mock bot. Source: `510 lines`.

**Fixtures:**

| Fixture | Description |
|---|---|
| `app(db)` | Creates FastAPI app via `create_app(bot)` with a `MagicMock` bot, adds a test Guild (discord_id="1", name="Test Guild") to the database |
| `client(app)` | `httpx.AsyncClient(transport=ASGITransport(app=app))` for HTTP calls |

**Test groups:**

| Group | Tests | Routes tested |
|---|---|---|
| Health & Ping | `test_health_check`, `test_health_ping`, `test_realtime_bridge_is_initialized`, `test_untrusted_host_is_rejected` | `GET /api/v1/health` |
| Guilds | `test_list_guilds` | `GET /api/v1/guilds` |
| Module toggle | `test_module_toggle_updates_only_the_target_guild` | `POST /api/v1/guilds/{id}/modules/{name}/toggle` |
| Config save | `test_saving_fresh_module_config_preserves_default_enabled_state` | `PUT /api/v1/guilds/{id}/modules/{name}` |
| Role access | `test_module_role_access_override_enforces_and_resets_default` | `PATCH/DELETE /api/v1/guilds/{id}/modules/{name}/role-access` |
| Config validation | `test_module_config_validation_rejects_array_and_enum_type_drift` | Unit test of `_validate_config()` |
| Action forms | `test_module_action_fields_render_with_browser_valid_types` | `GET /guild/{id}/modules/{name}` (web) |
| Empty operate tab | `test_module_without_actions_has_no_operate_tab` | `GET /guild/{id}/modules/{name}` (web) |
| Moderation cases | `test_list_cases_empty`, `test_create_case_validation`, `test_get_case_not_found`, `test_delete_case_not_found` | Cases CRUD |
| Moderation warnings | `test_list_warnings` | `GET /api/v1/guilds/{id}/moderation/warnings` |
| Notes | `test_list_notes`, `test_note_edit_and_delete_persist`, `test_note_validation_preserves_existing_record` | Full notes CRUD |
| Settings | `test_get_settings` | `GET /api/v1/guilds/{id}/settings` |
| Modules | `test_list_modules` | `GET /api/v1/guilds/{id}/modules` |
| Manifest | `test_manifest` | `GET /api/v1/guilds/{id}/manifest` |
| Stats | `test_guild_stats` | `GET /api/v1/guilds/{id}/stats` |

### `tests/test_dashboard/test_frontend_a11y_contract.py`

Build-free accessibility and desktop viewport contract tests — no browser, no fixtures. Source: `122 lines`. Uses standard library only (re, pathlib).

| Test | What it checks |
|---|---|
| `test_templates_do_not_use_inline_click_handlers` | No `onclick=` in any `.html` file |
| `test_base_shell_has_skip_target_context_and_accessible_dialog` | `#main-content`, skip link, `role="alertdialog"`, `aria-modal`, `aria-labelledby`, `aria-describedby` in `base.html` |
| `test_all_declared_tabs_have_relationship_and_keyboard_controller` | All `role="tab"` buttons have `aria-controls`; `main.js` handles ArrowRight/Left/Home/End |
| `test_modules_receive_native_workspace_content_and_live_action_forms` | `module_detail.html` uses generic `module_name` variable, has workspace tabs, loads `module-workspace.js` |
| `test_workspace_omits_empty_operate_tab_and_updates_toggle_in_place` | Operate tab hidden when no actions; toggle updates badge without `window.location.reload` |
| `test_moderation_danger_zones_are_contextual_to_their_tabs` | Danger zone purge buttons scoped to correct tabs (audit-logs/attachments in workspace, voice-history in voice tab) |
| `test_controls_added_by_workspace_have_programmatic_names` | Inputs associated via `for="{{ field_id }}"` / `id="{{ field_id }}"` |
| `test_desktop_viewport_and_zoom_contract_is_present` | All boundary breakpoints present in CSS (1024–1920); `prefers-reduced-motion`; `container-type: inline-size` |
| `test_guild_images_are_intrinsic_not_fixed_height` | Guild images use `width: 100%; height: auto`, no hard-coded heights |
| `test_changed_static_assets_have_cache_versions` | `main.css`, `main.js`, `shortcuts.js`, `module-workspace.js` referenced with `?v=N` query param |

### `tests/test_services/test_realtime_bridge.py`

Integration tests for EventBus producers and the SSE bridge. Source: `97 lines`.

| Test | What it checks |
|---|---|
| `test_event_bus_bridge_delivers_supported_events_to_only_the_target_guild` | Events delivered only to subscribed guild's queue; `ticket_created` not in `EVENT_MAP` |
| `test_create_case_producer_reaches_realtime_bridge` | `BarkContext.create_case` → EventBus → RealtimeBridge → SSE formatted message |
| `test_automod_producer_emits_guild_scoped_event` | ModerationModule automod triggers → EventBus → RealtimeBridge |

## Testing Patterns

### Async Fixture Pattern

Uses `pytest_asyncio` for async fixtures. Async fixtures use `@pytest_asyncio.fixture`, async tests use `@pytest.mark.asyncio`. The `db` fixture (from `conftest.py`) initializes the database before each test function and tears it down after.

```python
@pytest_asyncio.fixture
async def app(db):
    from dashboard import create_app
    # ... create mock bot ...
    dashboard_app = create_app(bot)
    return dashboard_app.app

@pytest_asyncio.fixture
async def client(app):
    from httpx import AsyncClient, ASGITransport
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
```

### Client Fixture Pattern

The `client` fixture wraps the FastAPI app with `httpx.AsyncClient` using `ASGITransport`. Tests call endpoints directly:

```python
@pytest.mark.asyncio
async def test_list_guilds(client):
    resp = await client.get("/api/v1/guilds")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
```

### AST-Based Contract Pattern

`test_frontend_a11y_contract.py` reads HTML template and JS/CSS source files directly (no server, no browser) and uses regex/string assertions to verify structural contracts:

```python
def test_base_shell_has_skip_target_context_and_accessible_dialog():
    html = source(TEMPLATES / "base.html")
    assert 'href="#main-content"' in html
    assert 'id="main-content"' in html and 'tabindex="-1"' in html
```

### Mock Bot Pattern

API tests mock the entire bot with `unittest.mock.MagicMock` + `AsyncMock`:

```python
bot = MagicMock()
bot.is_ready.return_value = True
bot.guilds = []
bot.modules = MagicMock()
bot.modules.event_bus = MagicMock()
bot.modules.event_bus.get_subscribers.return_value = {}
```

## Adding New Tests

1. **API endpoint tests**: Add a test function to `tests/test_dashboard/test_api.py`. Use the existing `client` fixture. Follow the pattern: call endpoint, assert status code, assert JSON response shape.
2. **Frontend contract tests**: Add a test function to `tests/test_dashboard/test_frontend_a11y_contract.py`. Read source files with `source(path)` helper, assert HTML/CSS/JS contract with `assert`.
3. **Service tests**: Add a test file in `tests/test_services/`. Use `@pytest.mark.asyncio` and import the service directly.
4. **New test files**: Create a `.py` file in the appropriate `tests/` subdirectory. The `conftest.py` fixtures are automatically available.
