"""Image payload validation by magic bytes.

Client-supplied Content-Type is not evidence — a caller can label arbitrary
bytes as image/*. Sniff the payload before persisting or sending to Discord.
"""

from __future__ import annotations

_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"
_GIF87 = b"GIF87a"
_GIF89 = b"GIF89a"
_RIFF = b"RIFF"


def sniff_image(data: bytes) -> str | None:
    """Return a file extension for a real image payload, or None."""
    if not data:
        return None
    if data.startswith(_PNG):
        return ".png"
    if data.startswith(_JPEG):
        return ".jpg"
    if data.startswith(_GIF87) or data.startswith(_GIF89):
        return ".gif"
    if data.startswith(_RIFF) and len(data) >= 12 and data[8:12] == b"WEBP":
        return ".webp"
    return None


def is_image(data: bytes) -> bool:
    return sniff_image(data) is not None
