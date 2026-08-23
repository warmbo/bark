"""App-wide Jinja template globals shared by every dashboard page.

Each web route module builds its OWN ``Jinja2Templates`` env (there is no
single shared env), so instance-aware globals must be registered on each one.
Call :func:`install` right after creating the env so templates like base.html
can read fresh instance state on every render.
"""

from __future__ import annotations

from fastapi.templating import Jinja2Templates


def install(templates: Jinja2Templates) -> None:
    """Attach instance-aware globals to one template environment."""

    def _wallpaper_invert() -> bool:
        from config import config
        from services.wallpaper_store import is_wallpaper_inverted

        return is_wallpaper_inverted(config.data_dir)

    templates.env.globals["wallpaper_invert"] = _wallpaper_invert
