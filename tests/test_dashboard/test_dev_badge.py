"""The DEV VERSION watermark renders only when BARK_DEV_BADGE is enabled.

Injected by an HTTP middleware (services/dev_overlay.py) so EVERY page on the
subdomain carries it — base.html pages, the standalone landing page, module
detail pages (which render via their own Jinja env without `config`), member
pages, error responses, and any future route. Template-level guarantees are
obsolete; the middleware is the single source of truth.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


def _make_guild(guild_id: int = 123456789) -> MagicMock:
    guild = MagicMock()
    guild.id = guild_id
    guild.name = "Test Guild"
    guild.icon = None
    return guild


def _make_module() -> MagicMock:
    module = MagicMock()
    module.version = "1.0.0"
    module.description = "Test module"
    module.author = "test"
    module.load_dashboard_config = AsyncMock(return_value={})
    module.get_settings_schema.return_value = {"properties": {}}
    module.get_extra_tabs.return_value = []
    module.get_commands.return_value = []
    module.get_events.return_value = []
    module.get_dashboard_pages.return_value = []
    module.get_actions.return_value = []
    module.get_about.return_value = {}
    return module


@pytest.fixture
def app(monkeypatch):
    import config
    from dashboard import create_app

    # Leave oauth2.enabled False (permissive mode) so every dashboard route
    # renders instead of 302-redirecting to /auth/login.
    monkeypatch.setattr(config.config.oauth2, "client_id", "")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "")

    bot = MagicMock()
    bot.guilds = []
    bot.user = None
    bot.is_ready.return_value = False
    bot.is_connected.return_value = False
    bot.wait_until_ready = AsyncMock()
    bot.get_guild.return_value = _make_guild()
    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {}
    bot.modules.get_module.return_value = _make_module()

    return create_app(bot)


@pytest.fixture
def client(app):
    return AsyncClient(transport=ASGITransport(app=app.app), base_url="http://test")


@pytest.mark.asyncio
async def test_landing_page_shows_dev_badge_when_enabled(app, monkeypatch, client):
    import config

    monkeypatch.setattr(config.config.instance, "dev_badge", True)
    async with client:
        response = await client.get("/")
    assert response.status_code == 200
    assert 'class="dev-badge-overlay"' in response.text
    assert "dev-badge-corner" not in response.text  # corner badge removed
    assert "DEV VERSION" in response.text  # tiled pattern (inline style data URI)


@pytest.mark.asyncio
async def test_landing_page_hides_dev_badge_when_disabled(app, monkeypatch, client):
    import config

    monkeypatch.setattr(config.config.instance, "dev_badge", False)
    async with client:
        response = await client.get("/")
    assert response.status_code == 200
    assert 'class="dev-badge-overlay"' not in response.text


@pytest.mark.asyncio
async def test_middleware_injects_badge_into_every_html_response(
    app, monkeypatch, client, db
):
    """Every HTML response on the subdomain carries the overlay — including
    module detail pages rendered WITHOUT `config` in context (the bug that
    motivated the middleware: web/modules.py uses its own Jinja env) and
    HTML error responses."""
    import config

    monkeypatch.setattr(config.config.instance, "dev_badge", True)

    routes = [
        "/",                                # landing (standalone page)
        "/dashboard",                       # dashboard home
        "/guild/123456789/settings",        # settings page
        "/guild/123456789/modules/roles",   # module detail via web/modules.py (no config ctx)
        "/guild/123456789/members",         # members page
        "/guild/123456789",                 # guild overview
        "/guild/999999/settings",           # error page (HTMLResponse 404)
    ]
    async with client:
        for route in routes:
            response = await client.get(route)
            assert 'class="dev-badge-overlay"' in response.text, (
                f"overlay missing on {route} (status {response.status_code})"
            )


@pytest.mark.asyncio
async def test_middleware_skips_non_html_responses(app, monkeypatch, client):
    """API JSON, static CSS, and JSON error responses must NOT get the overlay."""
    import config

    monkeypatch.setattr(config.config.instance, "dev_badge", True)
    async with client:
        api = await client.get("/api/v1/health")
        css = await client.get("/static/css/main.css")
        notfound = await client.get("/nonexistent-page-xyz")
    assert 'class="dev-badge-overlay"' not in api.text
    assert 'class="dev-badge-overlay"' not in css.text
    assert 'class="dev-badge-overlay"' not in notfound.text


@pytest.mark.asyncio
async def test_middleware_injects_into_bare_html_response(app, monkeypatch, client):
    """Bare HTML responses without a </body> tag (e.g. 'Guild not found')
    still get the overlay appended — the subdomain guarantee covers them."""
    import config

    monkeypatch.setattr(config.config.instance, "dev_badge", True)
    app.app.state.bot.get_guild.return_value = None  # short-circuit to bare 404 HTML
    async with client:
        response = await client.get("/guild/999999/modules/trivia")
    assert response.status_code == 404
    assert 'class="dev-badge-overlay"' in response.text


@pytest.mark.asyncio
async def test_middleware_does_not_double_inject(app, monkeypatch, client):
    """A response that already contains the overlay is left untouched."""
    import config

    monkeypatch.setattr(config.config.instance, "dev_badge", True)
    async with client:
        response = await client.get("/")
    assert response.text.count('class="dev-badge-overlay"') == 1


@pytest.mark.asyncio
async def test_invite_route_serves_bark_branded_og_page(app, monkeypatch, client):
    """GET /invite returns 200 HTML with Bark OG tags (so Discord's unfurl
    shows a Bark-branded card, not the Discord oauth2 preview), and includes a
    client-side redirect to the real Discord OAuth invite URL.

    The user-facing invite link is the branded {public_url}/invite, but the
    /invite route itself computes the actual Discord OAuth redirect target
    server-side (build_bot_invite_url) so the page never loops.
    """
    import config
    from services.dashboard_access import build_bot_invite_url

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    target = build_bot_invite_url("123", "")
    async with client:
        response = await client.get("/invite", follow_redirects=False)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # Bark-branded OpenGraph tags
    assert 'property="og:site_name" content="Bark"' in response.text
    assert "og:image" in response.text
    assert "bark-og.png" in response.text
    assert 'property="og:url"' in response.text
    # Client-side redirect to the real invite URL (humans). Jinja autoescape
    # turns & into &amp; inside the attribute; browsers decode it on refresh.
    escaped = target.replace("&", "&amp;")
    assert f'content="0; url={escaped}"' in response.text
    assert "window.location.replace" in response.text
    assert f'href="{escaped}"' in response.text


@pytest.mark.asyncio
async def test_invite_route_without_client_id_still_serves_branded_page(app, monkeypatch, client):
    """Without a client_id configured, /invite still serves the branded page
    (Discord can unfurl it) but with no client-side redirect."""
    import config

    monkeypatch.setattr(config.config.oauth2, "client_id", "")
    async with client:
        response = await client.get("/invite", follow_redirects=False)
    assert response.status_code == 200
    assert 'property="og:site_name" content="Bark"' in response.text
    assert "bark-og.png" in response.text
    assert "window.location.replace" not in response.text
