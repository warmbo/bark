"""Registry of loaded Bark modules and their page registrations.

Extracted from ``ModuleManager`` (single-responsibility split): this object owns
the ``name -> BarkModule`` map and the per-module dashboard page registrations.
``ModuleManager`` retains lifecycle/dispatch orchestration and delegates module
lookup/registration to this collaborator, which ``ModuleDiscovery`` fills at
startup/install time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from modules.base import BarkModule, PageRegistration


class ModuleRegistry:
    """Holds every loaded module and its page registrations."""

    def __init__(self) -> None:
        self._modules: dict[str, BarkModule] = {}
        self._page_registry: dict[str, list[PageRegistration]] = {}

    # ── Mutations ────────────────────────────────────

    def register(self, module: BarkModule) -> None:
        """Store a module and its page registrations (replaces any prior)."""
        self._modules[module.name] = module
        self._page_registry[module.name] = module.get_dashboard_pages()

    def drop(self, name: str) -> None:
        """Remove a module and its page registrations."""
        self._modules.pop(name, None)
        self._page_registry.pop(name, None)

    # ── Queries ──────────────────────────────────────

    def get(self, name: str) -> BarkModule | None:
        return self._modules.get(name)

    def has(self, name: str) -> bool:
        return name in self._modules

    def all(self) -> dict[str, BarkModule]:
        return dict(self._modules)

    def names(self) -> list[str]:
        return list(self._modules.keys())

    def enabled(self) -> dict[str, BarkModule]:
        return {n: m for n, m in self._modules.items() if m.enabled}

    def get_dashboard_pages(self) -> dict[str, list[PageRegistration]]:
        return dict(self._page_registry)
