"""Renderer registry — kind → callable(payload, theme) -> PIL.Image."""

from __future__ import annotations

from typing import Callable

from PIL import Image

from ..themes import Theme

RENDERERS: dict[str, Callable[[dict, Theme], Image.Image]] = {}


def register(kind: str) -> Callable:
    def deco(fn: Callable[[dict, Theme], Image.Image]) -> Callable:
        RENDERERS[kind] = fn
        return fn
    return deco


def render(kind: str, payload: dict, theme: Theme, **kwargs) -> Image.Image:
    fn = RENDERERS.get(kind)
    if fn is None:
        raise KeyError(f"no renderer for kind {kind!r}")
    return fn(payload, theme, **kwargs)


def available_kinds() -> list[str]:
    return sorted(RENDERERS)


# Eagerly import renderer modules so their @register decorators run.
from . import profile  # noqa: E402,F401  (must come after RENDERERS/register)
