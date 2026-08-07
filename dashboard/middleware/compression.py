"""Compression middleware for the Bark dashboard.

Applies gzip to non-streaming responses while leaving streaming responses
(SSE realtime feeds, ``text/event-stream``) untouched. Starlette's stock
GZipMiddleware buffers the entire body to compress it, which is fatal for
long-lived streams — the client would never receive an event until the stream
closes. Everything else (HTML pages, JSON API payloads, static CSS/JS) is
compressed as usual, cutting typical page payloads by ~70%.

Implementation mirrors Starlette's GZipResponder (delay the start message until
the first body chunk, then decide headers) with one difference: if the content
type is a streaming type we bypass compression entirely and forward every
message untouched, so SSE feeds stream live.

Middleware-order note: Starlette runs class middleware in reverse registration
order, so the *last* middleware added is the *outermost* (first to see the
request). Register this middleware last so compression applies to the final
response of every inner middleware.
"""

from __future__ import annotations

import gzip
import io

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SafeGzipMiddleware:
    """GZip everything except streaming responses (SSE feeds)."""

    def __init__(
        self,
        app: ASGIApp,
        minimum_size: int = 500,
        compresslevel: int = 9,
        *,
        skip_content_types: frozenset[str] = frozenset({"text/event-stream"}),
    ) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel
        self.skip = skip_content_types

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        await self.app(scope, receive, _ConditionalGzipSend(send, self))


class _ConditionalGzipSend:
    """Forward response messages; gzip the body only when safe to buffer."""

    def __init__(self, send: Send, middleware: "SafeGzipMiddleware") -> None:
        self.send = send
        self.middleware = middleware
        self.initial_message: Message | None = None
        self.started = False
        self.bypass = False
        self._gz: gzip.GzipFile | None = None
        self._gz_buf: io.BytesIO | None = None

    async def __call__(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            # Decide whether to bypass before sending anything.
            headers = dict(
                (k.lower(), v) for k, v in message.get("headers", [])
            )
            content_type = (
                headers.get(b"content-type", b"")
                .decode("latin-1", "replace")
                .split(";")[0]
                .strip()
            )
            already_encoded = b"content-encoding" in headers
            if content_type in self.middleware.skip or already_encoded:
                self.bypass = True
                await self.send(message)
            else:
                self.initial_message = message
            return

        if self.bypass:
            await self.send(message)
            return

        if message["type"] == "http.response.body":
            if self.initial_message is None:
                # No start message seen (shouldn't happen); pass through.
                await self.send(message)
                return
            await self._send_body(message)
            return

        # Informational messages etc.
        await self.send(message)

    async def _send_body(self, message: Message) -> None:
        body = message.get("body", b"")
        more_body = message.get("more_body", False)

        if not self.started:
            self.started = True
            initial = self.initial_message
            if initial is None:
                await self.send(message)
                return
            if len(body) < self.middleware.minimum_size and not more_body:
                # Small response: no compression, unchanged headers.
                await self.send(initial)
                await self.send(message)
                return
            # Large (or streaming) response: apply gzip from the first chunk.
            headers = list(initial.get("headers", []))
            headers = [
                (k, v)
                for k, v in headers
                if k.lower() not in (b"content-length", b"content-encoding")
            ]
            headers.append((b"content-encoding", b"gzip"))
            headers.append((b"vary", b"Accept-Encoding"))
            if not more_body:
                compressed = self._compress(body)
                headers.append((b"content-length", str(len(compressed)).encode()))
                await self.send(
                    {
                        "type": "http.response.start",
                        "status": initial["status"],
                        "headers": headers,
                    }
                )
                await self.send(
                    {
                        "type": "http.response.body",
                        "body": compressed,
                        "more_body": False,
                    }
                )
            else:
                # Streaming body: gzip incrementally, no content-length.
                await self.send(
                    {
                        "type": "http.response.start",
                        "status": initial["status"],
                        "headers": headers,
                    }
                )
                self._gz_buf = io.BytesIO()
                self._gz = gzip.GzipFile(
                    mode="wb",
                    fileobj=self._gz_buf,
                    compresslevel=self.middleware.compresslevel,
                )
                self._gz.write(body)
                await self._flush(final=False)
            return

        if self._gz is not None:
            self._gz.write(body)
            if not more_body:
                # Close first: gzip writes its trailer (CRC + size) on close,
                # which must reach the client for the stream to be valid.
                self._gz.close()
                self._gz = None
            await self._flush(final=not more_body)

    def _compress(self, data: bytes) -> bytes:
        return gzip.compress(data, compresslevel=self.middleware.compresslevel)

    async def _flush(self, *, final: bool) -> None:
        assert self._gz_buf is not None
        if self._gz is not None:
            self._gz.flush()
        data = self._gz_buf.getvalue()
        self._gz_buf.seek(0)
        self._gz_buf.truncate()
        await self.send(
            {"type": "http.response.body", "body": data, "more_body": not final}
        )
