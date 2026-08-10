"""Font resolution for the renderers.

Priority: bundled ``assets/fonts/`` → system font dirs → role fallback.
Theme JSONs reference font *filenames*; roles map to fallback candidates so
the renderer never crashes when a font is missing.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFont

ASSETS_FONTS = Path(__file__).resolve().parent / "assets" / "fonts"

_SYSTEM_DIRS = [
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/noto"),
    Path("/usr/share/fonts/truetype/liberation"),
    Path("/usr/share/fonts/truetype/ubuntu"),
]

FALLBACKS: dict[str, list[str]] = {
    "display": ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"],
    "display_regular": ["DejaVuSans.ttf", "LiberationSans-Regular.ttf"],
    "mono": ["DejaVuSansMono-Bold.ttf", "NotoSansMono-Bold.ttf"],
    "mono_regular": ["DejaVuSansMono.ttf", "NotoSansMono-Regular.ttf"],
}

EMOJI_FONT_NAMES = ["NotoColorEmoji.ttf", "NotoColorEmoji-Regular.ttf"]

_cache: dict[tuple[str, int, str], ImageFont.FreeTypeFont] = {}


def resolve_path(role: str, theme_fonts: dict, size: int = 16) -> str:
    """Absolute path for a logical font role, honoring the theme's filenames."""
    wanted = theme_fonts.get("display" if role.startswith("display") else "mono")
    if wanted:
        bundled = ASSETS_FONTS / wanted
        if bundled.is_file():
            return str(bundled)
        for d in _SYSTEM_DIRS:
            p = d / wanted
            if p.is_file():
                return str(p)
    for cand in FALLBACKS.get(role, FALLBACKS["display"]):
        for d in _SYSTEM_DIRS:
            p = d / cand
            if p.is_file():
                return str(p)
    raise FileNotFoundError(f"no font for role {role!r} (theme {theme_fonts})")


def font(role: str, size: int, theme_fonts: dict) -> ImageFont.FreeTypeFont:
    key = (role, size, theme_fonts.get("display", ""), theme_fonts.get("mono", ""))
    if key not in _cache:
        _cache[key] = ImageFont.truetype(resolve_path(role, theme_fonts, size), size)
    return _cache[key]


def emoji_font_path() -> Path | None:
    for name in EMOJI_FONT_NAMES:
        bundled = ASSETS_FONTS / name
        if bundled.is_file():
            return bundled
        for d in _SYSTEM_DIRS:
            p = d / name
            if p.is_file():
                return p
    return None


def has_emoji_font() -> bool:
    return emoji_font_path() is not None


# Noto Color Emoji is a CBDT bitmap font: it only loads at its embedded
# strike sizes, so arbitrary sizes must be scaled from a rendered glyph.
_EMOJI_STRIKES = (128, 109, 96, 64, 32)


def emoji_glyph(char: str, size: int) -> Image.Image | None:
    """Render a color-emoji glyph at ``size`` px, or None when unavailable."""
    from PIL import Image, ImageDraw

    path = emoji_font_path()
    if path is None:
        return None
    fnt = None
    for strike in _EMOJI_STRIKES:
        try:
            fnt = ImageFont.truetype(str(path), strike)
            break
        except OSError:
            continue
    if fnt is None:
        return None
    canvas = Image.new("RGBA", (strike * 2, strike * 2), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((strike, strike), char, font=fnt,
                                fill=(255, 255, 255, 255), anchor="mm")
    bbox = canvas.getbbox()
    if not bbox:
        return None
    glyph = canvas.crop(bbox)
    ratio = size / max(glyph.size)
    if ratio != 1.0:
        glyph = glyph.resize(
            (max(1, int(glyph.width * ratio)), max(1, int(glyph.height * ratio))),
            Image.LANCZOS,
        )
    return glyph


def strip_non_ascii(text: str) -> str:
    """Drop glyphs we cannot render without the emoji/unicode font."""
    return "".join(ch for ch in text if ord(ch) < 0x2500)
