"""Theme registry — single Bark theme (black/white/blue, dashboard tokens).

Design directive (cody, 2026-08-10): focus on ONE theme — mostly black and
white with hints of blue, matching the Bark dashboard. Runtime overrides can
still drop JSON files into ``data/themes/`` (same format); ``extends`` allows
derived themes, so seasonal/custom variants can return later without touching
code. The default and only shipped theme is ``bark``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("bark.media.themes")

BUNDLED_THEMES_DIR = Path(__file__).resolve().parent / "assets" / "themes"

DEFAULT_THEME = "bark"


@dataclass(frozen=True)
class Theme:
    name: str
    label: str
    palette: dict = field(default_factory=dict)
    background: dict = field(default_factory=dict)
    avatar: dict = field(default_factory=dict)
    fonts: dict = field(default_factory=dict)
    motion: dict = field(default_factory=dict)
    extends: str | None = None

    def merged(self) -> "Theme":
        """Return a fully-resolved theme (inherits from ``extends`` chain)."""
        base = self
        seen = {self.name}
        chain = [self]
        while base.extends and base.extends not in seen:
            parent = _load_theme(base.extends)
            if parent is None:
                break
            seen.add(parent.name)
            chain.append(parent)
            base = parent
        return Theme(
            name=self.name,
            label=self.label,
            palette=_merge(chain, "palette"),
            background=_merge(chain, "background"),
            avatar=_merge(chain, "avatar"),
            fonts=_merge(chain, "fonts"),
            motion=_merge(chain, "motion"),
        )

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "palette": self.palette,
            "background": self.background,
            "avatar": self.avatar,
            "fonts": self.fonts,
            "motion": self.motion,
        }


def _merge(chain: list[Theme], key: str) -> dict:
    """Merge ``key`` across the chain child-over-parent."""
    out: dict = {}
    for theme in reversed(chain):
        out.update(theme.__dict__.get(key) or {})
    return out


def _load_theme(name: str) -> Theme | None:
    for directory in (BUNDLED_THEMES_DIR, _data_themes_dir()):
        path = directory / f"{name}.json"
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("theme %s unreadable (%s)", name, exc)
            return None
        return Theme(
            name=raw.get("name", name),
            label=raw.get("label", name),
            palette=raw.get("palette") or {},
            background=raw.get("background") or {},
            avatar=raw.get("avatar") or {},
            fonts=raw.get("fonts") or {},
            motion=raw.get("motion") or {},
            extends=raw.get("extends"),
        )
    return None


def _data_themes_dir() -> Path:
    from .config import get_config
    return Path(get_config().data_dir) / "themes"


def get_theme(name: str) -> Theme | None:
    theme = _load_theme(name)
    return theme.merged() if theme else None


def resolve_theme(name: str | None = None) -> Theme:
    """Resolve a theme name; unknown/missing names fall back to ``bark``."""
    if name:
        theme = get_theme(name)
        if theme:
            return theme
        logger.warning("theme %r unavailable — falling back to %s", name, DEFAULT_THEME)
    fallback = get_theme(DEFAULT_THEME)
    if fallback is None:  # belt and braces: bare default so the renderer never crashes
        return Theme(
            name=DEFAULT_THEME, label="Bark",
            palette={"bg": "#14141a", "bg2": "#1b1b23", "fg": "#ffffff",
                     "muted": "#a8a8b3", "accent": "#3b82f6", "accent2": "#60a5fa"},
            background={"style": "gradient", "noise": 0.03, "shapes": True, "scanlines": True},
            avatar={"frame": "round", "border_color": "accent"},
            fonts={}, motion={"style": "none", "duration_frames": 1},
        )
    return fallback


def list_themes() -> list[dict]:
    """All themes on disk: {name, label, seasonal} (seasonal always False now)."""
    out = []
    for path in sorted(BUNDLED_THEMES_DIR.glob("*.json")):
        theme = _load_theme(path.stem)
        if theme:
            out.append({"name": theme.name, "label": theme.label, "seasonal": False})
    for path in sorted(_data_themes_dir().glob("*.json")) if _data_themes_dir().is_dir() else []:
        theme = _load_theme(path.stem)
        if theme and not any(t["name"] == theme.name for t in out):
            out.append({"name": theme.name, "label": theme.label, "seasonal": False})
    return out
