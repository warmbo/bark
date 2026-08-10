"""T1 — static profile card renderer (Pillow), sharp-edged dashboard card.

1024×1792 portrait card. Design logic mirrors the Bark dashboard: a stack of
translucent glass panels with 1px borders over a dark gradient backdrop,
blue accent, uppercase mono labels, JetBrains Mono. SHARP EDGES everywhere
on the chrome (design directive 2026-08-10); only avatars/badges stay round
(Discord identity marks).

REAL-DATA ONLY: every field drawn maps to something bark can actually obtain.
  user.*            → Discord API (live member/user object, plugin-supplied)
  reputation.*      → reputation_profiles + reputation_tiers tables
  badges            → reputation_awards ⋈ reputation_rewards
  activity bars     → reputation_events (message/reaction/thanks/voice rows)
  favorites         → reputation_events.channel_id counts (+ live names)
Nothing else is rendered — no Nitro/boost/global-badge fiction.

Layout (top → bottom), all panels sharp rects:
  outer card (glass, border, bracket corners)
  IDENTITY panel     — avatar + tier-progress ring + status dot,
                       display name, @username · joined <Mon YYYY> · member for Xy Ym
  TIER PROGRESS panel — tier + LVL squares, progress bar, score → next tier
  STATISTICS panel   — 2×2 tiles (messages / reactions / thanks / voice)
  ACTIVITY panel     — 7-day bars
  BADGES · TOP CHANNELS panel — medallions left, chips right
  footer

Missing data hides sections cleanly (no empty boxes).
"""

from __future__ import annotations

import random
import re
from datetime import date, datetime, timezone

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..fonts import emoji_glyph, font, has_emoji_font
from ..themes import Theme
from . import register

CARD_W, CARD_H = 1024, 1792
CARD = (24, 24, CARD_W - 24, CARD_H - 24)

# sharp glass panels (x0, y0, x1, y1)
PANEL_IDENTITY = (64, 64, 960, 512)
PANEL_TIER = (64, 540, 960, 680)
PANEL_STATS = (64, 708, 960, 1062)
PANEL_ACTIVITY = (64, 1090, 960, 1372)
PANEL_BOTTOM = (64, 1400, 960, 1612)

PANEL_PAD = 32
CONTENT_X0 = PANEL_STATS[0] + PANEL_PAD           # 96
CONTENT_X1 = PANEL_STATS[2] - PANEL_PAD           # 928
CONTENT_W = CONTENT_X1 - CONTENT_X0               # 832

AVATAR_CENTER = (CARD_W // 2, 240)
AVATAR_R = 150
AVATAR_SIZE = AVATAR_R * 2
RING_R = AVATAR_R + 16
STATUS_COLORS = {"online": "#22c55e", "idle": "#eab308", "dnd": "#ef4444",
                 "offline": "#5c5c66"}

_RGBA_RE = re.compile(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)")


# ── color / drawing helpers ──────────────────────────────────────────────

def _rgb(color, alpha: int = 255) -> tuple:
    """Hex (#rrggbb) or rgba() → (r, g, b, a) tuple."""
    if isinstance(color, str) and color.startswith("rgba"):
        m = _RGBA_RE.match(color)
        if m:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)),
                    int(float(m.group(4)) * 255))
        color = "#888888"
    color = (color or "#888888").lstrip("#")
    r, g, b = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    return (r, g, b, alpha)


def _with_alpha(rgb: tuple, alpha: int) -> tuple:
    return (rgb[0], rgb[1], rgb[2], alpha)


def _vertical_gradient(w: int, h: int, top: tuple, bottom: tuple) -> Image.Image:
    img = Image.new("RGBA", (w, h))
    px = img.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        c = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(w):
            px[x, y] = (c[0], c[1], c[2], 255)
    return img


def _noise(img: Image.Image, density: float, seed: int = 7) -> Image.Image:
    rng = random.Random(seed)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    n = int(img.size[0] * img.size[1] * density)
    for _ in range(n):
        x, y = rng.randint(0, img.size[0] - 1), rng.randint(0, img.size[1] - 1)
        d.point((x, y), fill=(255, 255, 255, rng.randint(6, 24)))
    return Image.alpha_composite(img, overlay)


def _scanlines(img: Image.Image, spacing: int = 5, alpha: int = 12) -> Image.Image:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for y in range(0, img.size[1], spacing):
        d.line([(0, y), (img.size[0], y)], fill=(0, 0, 0, alpha))
    return Image.alpha_composite(img, overlay)


def _glow_circle(img: Image.Image, center: tuple, radius: int, rgb: tuple,
                 intensity: int = 50, blur: int = 60) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    cx, cy = center
    ImageDraw.Draw(layer).ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                                  fill=_with_alpha(rgb, intensity))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    img.alpha_composite(layer)


def _draw_text(img: Image.Image, xy: tuple, text: str, fnt: ImageFont.FreeTypeFont,
               fill: tuple, anchor: str = "la") -> None:
    ImageDraw.Draw(img).text(xy, text, font=fnt, fill=fill, anchor=anchor)


def _tracked_width(fnt: ImageFont.FreeTypeFont, text: str, tracking: int) -> float:
    return sum(fnt.getlength(ch) for ch in text) + tracking * max(len(text) - 1, 0)


def _draw_tracked(img: Image.Image, xy: tuple, text: str, fnt: ImageFont.FreeTypeFont,
                  fill: tuple, tracking: int = 5, center: bool = False) -> None:
    """Uppercase micro-labels with manual letter spacing (HUD style)."""
    d = ImageDraw.Draw(img)
    x, y = xy
    if center:
        x -= _tracked_width(fnt, text, tracking) / 2
    for ch in text:
        d.text((x, y), ch, font=fnt, fill=fill, anchor="lm")
        x += fnt.getlength(ch) + tracking


def _corner_brackets(d: ImageDraw.ImageDraw, box: tuple, color: tuple,
                     length: int = 18, width: int = 3) -> None:
    """HUD targeting brackets at the four corners of ``box``."""
    x0, y0, x1, y1 = box
    for cx, cy, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1),
                           (x0, y1, 1, -1), (x1, y1, -1, -1)):
        d.line([(cx, cy + dy * length), (cx, cy)], fill=color, width=width)
        d.line([(cx, cy), (cx + dx * length, cy)], fill=color, width=width)


def _sharp_box(img: Image.Image, box: tuple, fill: tuple | None,
               outline: tuple | None = None, width: int = 1) -> None:
    """Sharp-edged box, alpha-composited so translucent fills BLEND with the
    content beneath. (ImageDraw fills replace pixels; drawing directly would
    wipe the avatar/name under the glass panels.)"""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if outline is not None:
        d.rectangle(box, fill=fill, outline=outline, width=width)
    else:
        d.rectangle(box, fill=fill)
    img.alpha_composite(layer)


def _panel(img: Image.Image, box: tuple, theme: Theme,
           header: str | None = None, header_color: tuple | None = None) -> ImageDraw.ImageDraw:
    """Glass panel (sharp) with an optional tracked header inside top-left."""
    p = theme.palette
    _sharp_box(img, box, fill=_rgb(p.get("glass", "rgba(255,255,255,0.04)")),
               outline=_rgb(p.get("glass_border", "rgba(255,255,255,0.09)")))
    if header:
        _draw_tracked(img, (box[0] + PANEL_PAD, box[1] + 30), header,
                      font("mono_regular", 16, theme.fonts),
                      _rgb(header_color or p.get("muted2", "#d6d6dd")), tracking=5)
    return ImageDraw.Draw(img)


# ── background ────────────────────────────────────────────────────────────

def _draw_background(theme: Theme) -> Image.Image:
    p = theme.palette
    img = _vertical_gradient(CARD_W, CARD_H, _rgb("#0c0c10"), _rgb("#14141a"))
    accent = _rgb(p["accent"])
    d = ImageDraw.Draw(img)

    _glow_circle(img, AVATAR_CENTER, 360, accent, intensity=28, blur=120)

    # orbit rings top-right
    d.ellipse((CARD_W - 60, -260, CARD_W + 260, 60),
              outline=_with_alpha(accent, 24), width=1)
    d.ellipse((CARD_W - 130, -330, CARD_W + 330, 130),
              outline=_with_alpha(_rgb(p["accent2"]), 12), width=1)

    img = _noise(img, float(theme.background.get("noise", 0.03)))
    if theme.background.get("scanlines", True):
        img = _scanlines(img)

    # the CARD: sharp glass panel + bracket corners
    _sharp_box(img, CARD, fill=_rgb("rgba(255,255,255,0.02)"),
               outline=_rgb("rgba(255,255,255,0.10)"), width=1)
    _corner_brackets(d, CARD, _with_alpha(accent, 140), length=32, width=3)
    return img


# ── avatar ───────────────────────────────────────────────────────────────

def _avatar_mask(size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    return mask


def _placeholder_avatar(payload: dict, size: int, theme: Theme) -> Image.Image:
    p = theme.palette
    user = payload.get("user") or {}
    name = user.get("display_name") or user.get("username") or "?"
    initials = "".join(part[0] for part in name.split()[:2]).upper() or "?"
    img = _vertical_gradient(size, size, _rgb(p["accent"]), _rgb(p["accent2"]))
    d = ImageDraw.Draw(img)
    fnt = font("display", int(size * 0.40), theme.fonts)
    bbox = d.textbbox((0, 0), initials, font=fnt)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]), initials,
           font=fnt, fill=(255, 255, 255, 255))
    return img


def _draw_avatar(img: Image.Image, avatar: Image.Image | None, payload: dict,
                 theme: Theme) -> None:
    p = theme.palette
    accent = _rgb(p["accent"])
    cx, cy = AVATAR_CENTER
    rep = payload.get("reputation") or {}

    progress = rep.get("tier_progress")
    d = ImageDraw.Draw(img)
    d.ellipse((cx - RING_R, cy - RING_R, cx + RING_R, cy + RING_R),
              outline=_with_alpha(accent, 55), width=5)
    if progress is not None and progress > 0:
        _glow_circle(img, (cx, cy), RING_R + 22, accent, intensity=38, blur=28)
        start = -90
        end = -90 + 360 * min(max(float(progress), 0.0), 1.0)
        d.arc((cx - RING_R - 5, cy - RING_R - 5, cx + RING_R + 5, cy + RING_R + 5),
              start=start, end=end, fill=accent, width=8)

    if avatar is None:
        avatar = _placeholder_avatar(payload, AVATAR_SIZE, theme)
    avatar = avatar.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS).convert("RGBA")
    img.paste(avatar, (cx - AVATAR_R, cy - AVATAR_R), _avatar_mask(AVATAR_SIZE))

    presence = (payload.get("user") or {}).get("presence", "offline")
    dot_r = 26
    dot_xy = (cx + AVATAR_R - 24, cy + AVATAR_R - 24)
    d.ellipse((dot_xy[0] - dot_r, dot_xy[1] - dot_r, dot_xy[0] + dot_r, dot_xy[1] + dot_r),
              fill="#14141a")
    d.ellipse((dot_xy[0] - dot_r + 5, dot_xy[1] - dot_r + 5,
               dot_xy[0] + dot_r - 5, dot_xy[1] + dot_r - 5),
              fill=_rgb(STATUS_COLORS.get(presence, STATUS_COLORS["offline"])))


# ── formatting helpers ────────────────────────────────────────────────────

def _fmt_int(n) -> str:
    n = int(n or 0)
    if n >= 1000:
        return f"{n / 1000:.1f}k" if n % 1000 else f"{n // 1000}k"
    return str(n)


def _fmt_voice(minutes: int) -> str:
    minutes = int(minutes or 0)
    h, m = divmod(minutes, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _fmt_member_for(joined_at, today: date | None = None) -> str | None:
    """'2y 7m' from a joined_at timestamp (real: member.joined_at)."""
    if not joined_at:
        return None
    try:
        joined = datetime.fromisoformat(str(joined_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    today = today or datetime.now(timezone.utc).date()
    joined_d = joined.date()
    if joined_d > today:
        return None
    months = (today.year - joined_d.year) * 12 + (today.month - joined_d.month)
    if today.day < joined_d.day:
        months -= 1
    if months < 1:
        return None
    years, rem = divmod(months, 12)
    if years:
        return f"{years}y {rem}m"
    return f"{rem}m"


# ── identity panel ────────────────────────────────────────────────────────

def _draw_identity(img: Image.Image, payload: dict, theme: Theme) -> None:
    p = theme.palette
    user = payload.get("user") or {}
    rep = payload.get("reputation") or {}
    _panel(img, PANEL_IDENTITY, theme)

    display = user.get("display_name") or user.get("username") or "Unknown"
    fnt_name = font("display", 54, theme.fonts)
    symbol = rep.get("tier_symbol") or ""
    name_x = CARD_W / 2
    glyph = emoji_glyph(symbol, 38) if symbol and has_emoji_font() else None
    if glyph:
        name_x -= 30
    _draw_text(img, (name_x, 444), display, fnt_name, _rgb(p["fg"]), anchor="mm")
    if glyph:
        img.paste(glyph, (int(CARD_W / 2 + _tracked_width(fnt_name, display, 0) / 2 + 16
                              - glyph.width / 2),
                          int(444 - glyph.height / 2)), glyph)

    sub = f"@{user.get('username') or user.get('id')}"
    if user.get("joined_at"):
        try:
            joined = datetime.fromisoformat(str(user["joined_at"]).replace("Z", "+00:00"))
            sub += f"  ·  joined {joined.strftime('%b %Y')}"
        except ValueError:
            pass
    duration = _fmt_member_for(user.get("joined_at"))
    if duration:
        sub += f"  ·  member for {duration}"
    _draw_text(img, (CARD_W / 2, 490), sub, font("display_regular", 22, theme.fonts),
               _rgb(p["muted"]), anchor="mm")


# ── tier progress panel ───────────────────────────────────────────────────

def _draw_tier(img: Image.Image, payload: dict, theme: Theme) -> None:
    p = theme.palette
    rep = payload.get("reputation") or {}
    d = _panel(img, PANEL_TIER, theme, header="TIER PROGRESS")

    # tier + LVL sharp squares, right-aligned in the header row
    tier_name = rep.get("tier") or "unranked"
    tier_color = _rgb(rep.get("tier_color") or p["accent"])
    fnt_pill = font("display_regular", 22, theme.fonts)
    pills = []
    if rep:
        pills.append((f" {tier_name} ", tier_color))
        pills.append((f" LVL {rep.get('level', 0)} ", _rgb(p["accent2"])))
    else:
        pills.append((" NO DATA ", _rgb(p["muted"])))
    widths = [d.textlength(t, font=fnt_pill) + 20 for t, _ in pills]
    total = sum(widths) + 10 * (len(pills) - 1)
    x = CONTENT_X1 - total
    for (text, color), w in zip(pills, widths):
        _sharp_box(img, (x, 556, x + w, 600),
                   fill=_with_alpha(color, 18), outline=_with_alpha(color, 120))
        _draw_text(img, (x + w / 2, 578), text, fnt_pill, _rgb(p["fg"]), anchor="mm")
        x += w + 10

    if not rep or rep.get("tier_progress") is None:
        return
    # progress bar (sharp)
    bar_y = 620
    bar_h = 30
    accent = _rgb(rep.get("tier_color") or p["accent"])
    _sharp_box(img, (CONTENT_X0, bar_y, CONTENT_X1, bar_y + bar_h),
               fill=_with_alpha(_rgb(p["fg"]), 12), outline=_with_alpha(accent, 80))
    progress = min(max(float(rep.get("tier_progress") or 0.0), 0.0), 1.0)
    if progress > 0:
        fill_w = max(int((CONTENT_X1 - CONTENT_X0) * progress), bar_h)
        d.rectangle((CONTENT_X0, bar_y, CONTENT_X0 + fill_w, bar_y + bar_h), fill=accent)
        _glow_circle(img, (CONTENT_X0 + fill_w / 2, bar_y + bar_h / 2), 56, accent,
                     intensity=60, blur=40)

    score = int(rep.get("score") or 0)
    nxt = rep.get("next_tier")
    fnt_lbl = font("mono_regular", 22, theme.fonts)
    if nxt:
        target = int(rep.get("next_tier_min_score") or 0)
        label = f"{score:,} / {target:,} → {nxt.upper()}"
    else:
        label = f"{score:,} PTS"
    _draw_text(img, (CONTENT_X1 - 14, bar_y + bar_h / 2 + 1), label, fnt_lbl,
               _rgb(p["muted2"]), anchor="rm")
    _draw_text(img, (CONTENT_X0 + 14, bar_y + bar_h / 2 + 1), f"LVL {rep.get('level', 0)}",
               font("mono", 22, theme.fonts), _rgb(p["fg"]), anchor="lm")

    _corner_brackets(d, (CONTENT_X0 - 6, bar_y - 6, CONTENT_X1 + 6, bar_y + bar_h + 6),
                     _with_alpha(accent, 110), length=14, width=2)


# ── statistics panel ──────────────────────────────────────────────────────

def _draw_stats(img: Image.Image, payload: dict, theme: Theme) -> None:
    p = theme.palette
    rep = payload.get("reputation") or {}
    d = _panel(img, PANEL_STATS, theme, header="STATISTICS")
    if not rep:
        _draw_text(img, (CONTENT_X0, PANEL_STATS[1] + 110), "no reputation data yet",
                   font("display_regular", 22, theme.fonts), _rgb(p["muted"]), anchor="lm")
        return
    tiles = [
        ("MESSAGES", _fmt_int(rep.get("messages")), "×"),
        ("REACTIONS", _fmt_int(rep.get("reactions")), "♥"),
        ("THANKS", _fmt_int(rep.get("thanks")), "★"),
        ("VOICE", _fmt_voice(rep.get("voice_minutes")), "◉"),
    ]
    tile_w, tile_h, gap = (CONTENT_W - 20) // 2, 118, 20
    fnt_lbl = font("mono_regular", 15, theme.fonts)
    fnt_val = font("mono", 44, theme.fonts)
    fnt_ico = font("display_regular", 24, theme.fonts)
    positions = [(CONTENT_X0, 772), (CONTENT_X0 + tile_w + gap, 772),
                 (CONTENT_X0, 910), (CONTENT_X0 + tile_w + gap, 910)]
    for i, ((label, value, icon), (x, y)) in enumerate(zip(tiles, positions)):
        accent = _rgb(p["accent"] if i % 2 == 0 else p["accent2"])
        _sharp_box(img, (x, y, x + tile_w, y + tile_h),
                   fill=_rgb(p["glass"]), outline=_rgb(p["glass_border"]))
        _corner_brackets(d, (x + 6, y + 6, x + tile_w - 6, y + tile_h - 6),
                         _with_alpha(accent, 150), length=12, width=2)
        _draw_tracked(img, (x + 28, y + 32), label, fnt_lbl, _rgb(p["muted"]), tracking=3)
        _draw_text(img, (x + 28, y + 84), value, fnt_val, _rgb(p["fg"]), anchor="lm")
        _draw_text(img, (x + tile_w - 28, y + 36), icon, fnt_ico,
                   _with_alpha(accent, 220), anchor="rm")
        d.line([(x + 28, y + tile_h - 10), (x + tile_w - 28, y + tile_h - 10)],
               fill=_with_alpha(accent, 80), width=1)


# ── activity panel ────────────────────────────────────────────────────────

def _draw_activity(img: Image.Image, payload: dict, theme: Theme) -> None:
    p = theme.palette
    activity = payload.get("activity") or {}
    bars = activity.get("bars_weekly") or []
    d = _panel(img, PANEL_ACTIVITY, theme, header="ACTIVITY · LAST 7 DAYS")
    if not bars:
        _draw_text(img, (CONTENT_X0, PANEL_ACTIVITY[1] + 110), "no activity yet",
                   font("display_regular", 22, theme.fonts), _rgb(p["muted"]), anchor="lm")
        return

    bar_w, gap, max_h = 76, 36, 130
    total_w = len(bars) * bar_w + (len(bars) - 1) * gap
    x0 = CONTENT_X0 + (CONTENT_W - total_w) / 2
    chart_top = 1152
    peak = max(max(bars), 1)
    accent, accent2 = _rgb(p["accent"]), _rgb(p["accent2"])
    for i, val in enumerate(bars):
        x = x0 + i * (bar_w + gap)
        h = max(int(max_h * val / peak), 8 if val else 4)
        color = accent if i % 2 == 0 else accent2
        if val == peak and val > 0:
            _glow_circle(img, (x + bar_w / 2, chart_top + max_h - h), 46, accent,
                         intensity=55, blur=32)
        _sharp_box(img, (x, chart_top + max_h - h, x + bar_w, chart_top + max_h),
                   fill=_with_alpha(color, 225 if val else 50))
    d.line([(CONTENT_X0, chart_top + max_h), (CONTENT_X1, chart_top + max_h)],
           fill=_with_alpha(_rgb(p["fg"]), 30), width=1)
    days = ["M", "T", "W", "T", "F", "S", "S"]
    for i, day in enumerate(days):
        x = x0 + i * (bar_w + gap) + bar_w / 2
        _draw_text(img, (x, chart_top + max_h + 24), day,
                   font("mono_regular", 16, theme.fonts), _rgb(p["muted"]), anchor="ma")


# ── bottom panel: badges + favorite channels ──────────────────────────────

def _draw_badges(img: Image.Image, payload: dict, theme: Theme) -> None:
    p = theme.palette
    badges = payload.get("badges") or []
    if not badges:
        return
    _draw_tracked(img, (CONTENT_X0, 1430), "BADGES",
                  font("mono_regular", 16, theme.fonts), _rgb(p["muted"]), tracking=5)
    r = 36
    gap = 22
    shown = badges[:4]  # 4 fit beside the channel chips; extras become +N
    x0 = CONTENT_X0 + 8
    d = ImageDraw.Draw(img)
    accent, accent2 = _rgb(p["accent"]), _rgb(p["accent2"])
    for i, badge in enumerate(shown):
        cx = x0 + r + i * (r * 2 + gap)
        cy = 1482
        color = accent if i % 2 == 0 else accent2
        d.ellipse((cx - r, cy - r, cx + r, cy + r),
                  fill=_with_alpha(color, 36),
                  outline=_with_alpha(color, 170), width=3)
        initial = (badge.get("name") or "?")[0].upper()
        fnt = font("display", 32, theme.fonts)
        bbox = d.textbbox((0, 0), initial, font=fnt)
        d.text((cx - (bbox[2] - bbox[0]) / 2 - bbox[0],
                cy - (bbox[3] - bbox[1]) / 2 - bbox[1]), initial,
               font=fnt, fill=(255, 255, 255, 255))
    if len(badges) > len(shown):
        cx = x0 + r + len(shown) * (r * 2 + gap) - gap
        _draw_text(img, (cx + 6, 1482), f"+{len(badges) - len(shown)}",
                   font("mono", 20, theme.fonts), _rgb(p["muted2"]), anchor="lm")


def _draw_favorites(img: Image.Image, payload: dict, theme: Theme) -> None:
    p = theme.palette
    favs = payload.get("favorites") or []
    if not favs:
        return
    fnt_lbl = font("mono_regular", 16, theme.fonts)
    fnt_name = font("display_regular", 20, theme.fonts)
    d = ImageDraw.Draw(img)
    _draw_tracked(img, (CONTENT_X1, 1430), "TOP CHANNELS", fnt_lbl,
                  _rgb(p["muted"]), tracking=5, center=True)

    chip_y = 1466
    chip_h = 44
    chips = []
    for fav in favs[:2]:
        name = fav.get("name") or f"#{str(fav.get('channel_id', '?')[:8])}"
        count = int(fav.get("count") or 0)
        chips.append(f"#{name}  ×{count}")
    widths = [d.textlength(t, font=fnt_name) + 36 for t in chips]
    total_w = sum(widths) + 12 * (len(chips) - 1)
    x = CONTENT_X1 - total_w
    accent = _rgb(p["accent"])
    for text, w in zip(chips, widths):
        _sharp_box(img, (x, chip_y, x + w, chip_y + chip_h),
                   fill=_with_alpha(accent, 14), outline=_with_alpha(accent, 90))
        _draw_text(img, (x + w / 2, chip_y + chip_h / 2), text, fnt_name,
                   _rgb(p["fg"]), anchor="mm")
        x += w + 12


# ── footer ────────────────────────────────────────────────────────────────

def _draw_footer(img: Image.Image, theme: Theme) -> None:
    p = theme.palette
    today = date.today().isoformat()
    text = f"BARK PROFILES · {theme.label.upper()} · {today}"
    fnt = font("mono_regular", 16, theme.fonts)
    d = ImageDraw.Draw(img)
    _draw_text(img, (CARD_W / 2, 1740), text, fnt,
               _with_alpha(_rgb(p["muted"]), 230), anchor="mm")
    d.line([(CARD_W / 2 - 100, 1766), (CARD_W / 2 + 100, 1766)],
           fill=_with_alpha(_rgb(p["accent"]), 100), width=2)
    d.rectangle((CARD_W / 2 - 4, 1762, CARD_W / 2 + 4, 1770), fill=_rgb(p["accent"]))


# ── entry point ──────────────────────────────────────────────────────────

def _flatten(img: Image.Image) -> Image.Image:
    """RGBA → RGB composited over the card's dark backdrop (convert("RGB")
    would just DROP alpha and leave translucent fills as opaque white)."""
    bg = Image.new("RGB", img.size, (12, 12, 16))
    bg.paste(img, mask=img.getchannel("A"))
    return bg


@register("profile")
def render_profile_card(payload: dict, theme: Theme,
                        avatar: Image.Image | None = None) -> Image.Image:
    """Render the vertical profile card. ``avatar`` may be a pre-fetched image."""
    img = _draw_background(theme)
    _draw_avatar(img, avatar, payload, theme)
    _draw_identity(img, payload, theme)
    _draw_tier(img, payload, theme)
    _draw_stats(img, payload, theme)
    _draw_activity(img, payload, theme)
    _draw_badges(img, payload, theme)
    _draw_favorites(img, payload, theme)
    _draw_footer(img, theme)
    return _flatten(img)
