"""Theme registry — single Bark theme."""

from services.media_engine.themes import DEFAULT_THEME, get_theme, list_themes, resolve_theme


def test_default_is_bark():
    assert DEFAULT_THEME == "bark"


def test_bark_theme_fields():
    theme = get_theme("bark")
    assert theme is not None
    assert theme.name == "bark"
    for key in ("bg", "bg2", "fg", "muted", "accent", "accent2"):
        assert theme.palette[key].startswith("#")
    assert theme.palette["bg"] == "#14141a"  # dashboard token
    assert theme.palette["accent"] == "#3b82f6"  # dashboard token
    assert theme.background["scanlines"] is True
    assert theme.fonts["mono"].endswith(".ttf")


def test_resolve_defaults_to_bark():
    assert resolve_theme(None).name == "bark"
    assert resolve_theme("bark").name == "bark"


def test_unknown_falls_back_to_default():
    theme = resolve_theme("does-not-exist")
    assert theme.name == DEFAULT_THEME


def test_list_themes_single():
    themes = list_themes()
    assert [t["name"] for t in themes] == ["bark"]
    assert themes[0]["seasonal"] is False
