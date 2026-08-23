"""Persistent wallpaper store — saves/loads the instance wallpaper treatment.

The dashboard backdrop is a single global image (bark-wallpaper.png), now
monochrome. The instance owner may optionally invert it (a light negative).
That choice is INSTANCE-GLOBAL (it brands every page), stored as a small JSON
file in the data directory, mirroring `presence_store`.

The invert flag is read server-side on every page render and emitted as
``data-wallpaper="invert"`` on <html> (see dashboard/__init__.py), which the
compiled CSS uses to swap ``--wallpaper-url`` to the inverted image.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("bark.services.wallpaper_store")


def _store_path(data_dir: Path) -> Path:
    return data_dir / "wallpaper.json"


def load_wallpaper(data_dir: Path) -> dict[str, Any]:
    """Load persisted wallpaper settings, or return defaults (not inverted)."""
    path = _store_path(data_dir)
    if not path.exists():
        return {"invert": False}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {"invert": False}
        return {"invert": bool(data.get("invert", False))}
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read wallpaper store, using defaults")
        return {"invert": False}


def is_wallpaper_inverted(data_dir: Path) -> bool:
    """True when the instance wallpaper should render inverted."""
    return load_wallpaper(data_dir).get("invert", False)


def save_wallpaper(data_dir: Path, invert: bool) -> None:
    """Persist the wallpaper invert choice to disk."""
    path = _store_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"invert": bool(invert)}, indent=2)
        )
        logger.info("Wallpaper saved: invert=%s", bool(invert))
    except OSError as exc:
        logger.error("Failed to save wallpaper: %s", exc)
