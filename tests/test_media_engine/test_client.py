"""Shared MediaEngineClient — transport-mocked tests."""

import httpx
import pytest

from services.media_engine.client import (
    MediaEngineClient,
    MediaEngineError,
    MediaEngineUnavailableError,
)


def _mock(handler) -> MediaEngineClient:
    return MediaEngineClient(
        base_url="http://engine", token="tok", poll_interval=0.01,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_render_polls_to_file():
    polls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/render":
            return httpx.Response(200, json={"job_id": "abc"})
        if request.url.path == "/v1/jobs/abc":
            polls["n"] += 1
            if polls["n"] < 3:
                return httpx.Response(200, json={"status": "rendering"})
            return httpx.Response(200, json={"status": "done", "file": "/tmp/out.png"})
        return httpx.Response(404)

    client = _mock(handler)
    path = await client.render("profile", "g1", "u1", payload={"user": {}})
    assert path == "/tmp/out.png"
    assert polls["n"] == 3


@pytest.mark.asyncio
async def test_render_error_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/render":
            return httpx.Response(200, json={"job_id": "x"})
        return httpx.Response(200, json={"status": "error", "error": "kaboom"})

    with pytest.raises(MediaEngineError, match="kaboom"):
        await _mock(handler).render("profile", "g1", "u1")


@pytest.mark.asyncio
async def test_render_timeout_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/render":
            return httpx.Response(200, json={"job_id": "x"})
        return httpx.Response(200, json={"status": "queued"})

    with pytest.raises(MediaEngineError, match="did not finish"):
        await _mock(handler).render("profile", "g1", "u1", cache_ttl=0)


@pytest.mark.asyncio
async def test_engine_down_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(MediaEngineUnavailableError):
        await _mock(handler).collect_payload("profile", "g1", "u1")


@pytest.mark.asyncio
async def test_health():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "version": "0.1.0"})

    assert await _mock(handler).health() is True


@pytest.mark.asyncio
async def test_health_false_when_down():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    assert await _mock(handler).health() is False


@pytest.mark.asyncio
async def test_collect_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tok"
        return httpx.Response(200, json={"reputation": {"score": 5.0},
                                         "activity": {}, "badges": [], "favorites": []})

    data = await _mock(handler).collect_payload("profile", "g1", "u1")
    assert data["reputation"]["score"] == 5.0
