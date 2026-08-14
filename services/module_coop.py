"""Optional cross-module cooperation registry.

Modules can advertise optional data providers and consume providers exposed by
other modules, without hard dependencies. If a provider is not registered (the
module isn't installed or isn't enabled for the guild), ``call()`` simply
returns ``None`` — cooperation degrades gracefully instead of erroring.

This is the mechanism that lets Bark plugins become *optional features* that
compose: a birthdays module can expose ``birthdays.upcoming`` and any other
module (or the dashboard) can render it when present, no coupling required.

Handlers are coroutines: ``async def handler(guild_id: int, **kwargs) -> dict | None``.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger("bark.coop")

ProviderHandler = Callable[..., Awaitable[dict | None]]


class ModuleCoop:
    """Thread-safe-ish registry of optional named data providers.

    One instance is shared across all modules via ``BarkContext.coop`` so any
    module can register or consume providers.
    """

    def __init__(self) -> None:
        self._providers: dict[str, ProviderHandler] = {}

    def register(self, provider_name: str, handler: ProviderHandler) -> None:
        self._providers[provider_name] = handler

    def unregister(self, provider_name: str) -> None:
        self._providers.pop(provider_name, None)

    def provides(self, provider_name: str) -> bool:
        return provider_name in self._providers

    def names(self) -> list[str]:
        return sorted(self._providers)

    async def call(self, provider_name: str, guild_id: int, **kwargs: Any) -> dict | None:
        """Invoke a provider, returning None when absent or on failure."""
        handler = self._providers.get(provider_name)
        if handler is None:
            return None
        try:
            result: Any = handler(guild_id, **kwargs)
            if hasattr(result, "__await__"):
                result = await result  # type: ignore[misc]
            return result
        except Exception:
            logger.exception("Coop provider '%s' failed for guild %s", provider_name, guild_id)
            return None
