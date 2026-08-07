"""SafeGzipMiddleware: compresses buffered responses, never SSE streams."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from dashboard.middleware.compression import SafeGzipMiddleware


class _StubApp:
    """Minimal ASGI app returning one of several canned responses."""

    def __init__(self, *, body: bytes, content_type: str, streaming: bool = False):
        self.body = body
        self.content_type = content_type
        self.streaming = streaming

    async def __call__(self, scope, receive, send):
        headers = [(b"content-type", self.content_type.encode())]
        await send(
            {"type": "http.response.start", "status": 200, "headers": headers}
        )
        if self.streaming:
            for chunk in [self.body[:3], self.body[3:6], self.body[6:]]:
                await send(
                    {"type": "http.response.body", "body": chunk, "more_body": True}
                )
            await send(
                {"type": "http.response.body", "body": b"", "more_body": False}
            )
        else:
            await send(
                {
                    "type": "http.response.body",
                    "body": self.body,
                    "more_body": False,
                }
            )


@pytest.mark.asyncio
async def test_compresses_large_html_response():
    body = b"<html>" + b"x" * 5000 + b"</html>"
    app = SafeGzipMiddleware(_StubApp(body=body, content_type="text/html"))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    # httpx auto-decompresses gzip bodies, so content is the original.
    assert response.content == body


@pytest.mark.asyncio
async def test_leaves_small_response_uncompressed():
    body = b"<p>tiny</p>"
    app = SafeGzipMiddleware(_StubApp(body=body, content_type="text/html"))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert response.content == body


@pytest.mark.asyncio
async def test_never_compresses_sse_stream():
    body = b"data: ping\n\n" * 20
    app = SafeGzipMiddleware(
        _StubApp(body=body, content_type="text/event-stream", streaming=True)
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    # The raw streamed body must be intact — gzip would have corrupted it.
    assert response.content == body


@pytest.mark.asyncio
async def test_compresses_streaming_non_sse_body():
    # A large non-SSE streaming body (e.g. file download) should still gzip.
    body = b"chunk-chunk-chunk-" * 500  # 9000 bytes
    app = SafeGzipMiddleware(
        _StubApp(body=body, content_type="application/octet-stream", streaming=True)
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    # httpx auto-decompresses gzip bodies, so content is the original.
    assert response.content == body


@pytest.mark.asyncio
async def test_respects_existing_content_encoding():
    body = b"already-encoded"

    class _PreEncoded(_StubApp):
        async def __call__(self, scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"text/html"),
                        (b"content-encoding", b"br"),
                    ],
                }
            )
            await send(
                {"type": "http.response.body", "body": body, "more_body": False}
            )

    wrapped = SafeGzipMiddleware(_PreEncoded(body=body, content_type="text/html"))
    async with AsyncClient(
        transport=ASGITransport(app=wrapped), base_url="http://test"
    ) as client:
        response = await client.get("/")
    assert response.headers["content-encoding"] == "br"
