"""T1 profile card renderer — vertical smoke + layout tests."""

import io

from datetime import date

from PIL import Image, ImageStat

from services.media_engine.renderers import available_kinds, render
from services.media_engine.renderers.profile import _fmt_member_for
from services.media_engine.themes import get_theme

PAYLOAD = {
    "user": {
        "id": "1", "display_name": "Cody Warmbo", "username": "cody",
        "avatar_url": None, "joined_at": "2024-01-05T18:30:00Z", "presence": "online",
    },
    "roles": [{"name": "Moderator", "color": 0x5865F2, "hoist": True}],
    "reputation": {
        "score": 1240.5, "level": 12, "tier": "Legend", "tier_symbol": "👑",
        "tier_color": "#ffb020", "tier_min_score": 1000.0, "next_tier": None,
        "next_tier_min_score": None, "tier_progress": 0.62,
        "weekly": 40.2, "monthly": 210.0, "thanks": 84, "messages": 4210,
        "reactions": 930, "voice_minutes": 1820,
    },
    "activity": {"bars_weekly": [3, 5, 2, 8, 6, 4, 7], "bars_monthly": [12, 18, 9, 40]},
    "badges": [{"name": "Early Member", "description": "", "icon": ""}],
    "favorites": [{"channel_id": "1", "name": "general", "count": 320}],
}

EMPTY_PAYLOAD = {
    "user": {"id": "2", "display_name": "", "username": "ghost"},
    "roles": [], "reputation": {}, "activity": {}, "badges": [], "favorites": [],
}


def _render(payload):
    theme = get_theme("bark")
    assert theme is not None
    return render("profile", payload, theme)


def test_kind_registered():
    assert "profile" in available_kinds()


def test_renders_vertical_dimensions():
    img = _render(PAYLOAD)
    assert img.size == (1024, 1792)
    assert img.mode == "RGB"


def test_render_is_non_blank():
    img = _render(PAYLOAD)
    stat = ImageStat.Stat(img)
    assert sum(stat.stddev) > 10


def test_render_is_deterministic():
    a = _render(PAYLOAD)
    b = _render(PAYLOAD)
    buf_a, buf_b = io.BytesIO(), io.BytesIO()
    a.save(buf_a, "PNG")
    b.save(buf_b, "PNG")
    assert buf_a.getvalue() == buf_b.getvalue()


def test_empty_payload_renders():
    img = _render(EMPTY_PAYLOAD)
    assert img.size == (1024, 1792)
    stat = ImageStat.Stat(img)
    assert sum(stat.stddev) > 5


def test_partial_reputation_renders():
    """Reputation present but tier progress missing (no tier curve) → no crash."""
    payload = dict(PAYLOAD)
    rep = dict(payload["reputation"])
    rep.pop("tier_progress")
    payload["reputation"] = rep
    img = _render(payload)
    assert img.size == (1024, 1792)


def test_bot_user_renders():
    payload = dict(PAYLOAD)
    payload["user"] = {**payload["user"], "is_bot": True, "presence": "dnd"}
    img = _render(payload)
    assert img.size == (1024, 1792)


def test_member_for_duration():
    assert _fmt_member_for("2024-01-05T00:00:00Z", today=date(2026, 8, 10)) == "2y 7m"
    assert _fmt_member_for("2026-07-01T00:00:00Z", today=date(2026, 8, 10)) == "1m"
    assert _fmt_member_for("2026-08-10T00:00:00Z", today=date(2026, 8, 10)) is None
    assert _fmt_member_for(None) is None
    assert _fmt_member_for("garbage") is None
