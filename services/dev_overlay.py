"""
Dev-build watermark injection — applied at the HTTP layer so EVERY page on the
subdomain carries the DEV VERSION overlay, regardless of which template or
Jinja environment rendered it (base.html pages, standalone landing, module
detail pages via web/modules.py, members, error pages, future routes).

Single source of truth for the overlay markup + CSS. The old template-level
approach ({% include "components/dev_badge.html" %}) could be bypassed by any
page whose renderer did not put `config` in the template context; a middleware
cannot be bypassed by page templates.
"""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import HTMLResponse

from config import config

logger = logging.getLogger("bark.dashboard")

# Self-contained overlay: tiled diagonal white "DEV VERSION" text, fixed,
# pointer-events: none, top z-index. The <style> ships inline so the overlay
# renders even on pages that do not load main.css (landing standalone page,
# bare error responses). Keep the data URI escaped exactly as served.
_OVERLAY_MARKUP = (
    '<style>\n'
    '.dev-badge-overlay {\n'
    '  position: fixed;\n'
    '  inset: 0;\n'
    '  z-index: 2147483000;\n'
    '  pointer-events: none;\n'
    "  background-image: url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 "
    'width=%22320%22 height=%22320%22 viewBox=%220 0 320 320%22><text x=%22160%22 y=%22160%22 '
    'transform=%22rotate(-30 160 160)%22 fill=%22%23ffffff%22 font-family=%22Inter,Arial,sans-serif%22 '
    'font-size=%2226%22 font-weight=%22800%22 letter-spacing=%224%22 text-anchor=%22middle%22 '
    'opacity=%220.04%22>DEV VERSION</text></svg>\');\n'
    '  background-size: 320px 320px;\n'
    '}\n'
    '</style>\n'
    '<div class="dev-badge-overlay" aria-hidden="true"></div>'
)

_MARKUP_BYTES = _OVERLAY_MARKUP.encode("utf-8")


async def dev_overlay_middleware(request: Request, call_next):
    """Inject the DEV VERSION overlay into every text/html response when
    config.instance.dev_badge is enabled.

    Skipped for non-HTML responses (API JSON, static assets, media) and for
    streaming responses (their body is not available to rewrite). Responses
    that already contain the overlay are left untouched (idempotent).
    """
    response = await call_next(request)
    if not config.instance.dev_badge:
        return response

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type:
        return response

    # call_next returns a _StreamingResponse wrapper; consume the body to
    # rewrite it, then hand back a fresh HTMLResponse. Once the iterator is
    # consumed the original response can no longer be sent, so ALWAYS rebuild
    # from the consumed bytes (even when unchanged).
    body_chunks = []
    async for chunk in response.body_iterator:
        body_chunks.append(chunk)
    body = b"".join(body_chunks)

    # Inject just before </body> so the overlay sits above the page content
    # (fixed positioning does not depend on DOM placement). Idempotent: skip
    # responses that already carry the overlay. Bare HTML responses (e.g.
    # "Module not found" without a <body> tag) get the markup appended —
    # a fixed-position overlay renders regardless of document structure.
    if body and b"dev-badge-overlay" not in body:
        if b"</body>" in body:
            new_body = body.replace(b"</body>", _MARKUP_BYTES + b"</body>", 1)
        else:
            new_body = body + _MARKUP_BYTES
    else:
        new_body = body

    headers = dict(response.headers)
    headers.pop("content-length", None)  # let Starlette recompute
    return HTMLResponse(
        content=new_body,
        status_code=response.status_code,
        headers=headers,
        media_type=response.media_type,
    )
