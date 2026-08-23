"""Regression tests for AutoMod config-cache invalidation on dashboard save.

The moderation module caches flat config (_config_cache) and rulesets
(_ruleset_cache) for 30s so the hot message path doesn't hit the DB every
message. A dashboard save MUST invalidate those caches immediately, otherwise
rules keep enforcing stale values for up to 30s.
"""

from types import SimpleNamespace

import pytest

from modules.moderation.module import ModerationModule


async def _async_noop(*args, **kwargs):
    return True


def _make_module() -> ModerationModule:
    # Minimal ctx: base __init__ reads only a few attributes; coop is optional.
    ctx = SimpleNamespace(
        coop=None,
        logger=__import__("logging").getLogger("test"),
        command_group="bark",
        get_module_config=lambda *a, **k: {},  # unused here
        save_module_config=_async_noop,
    )
    return ModerationModule(ctx)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_save_dashboard_config_invalidates_automod_caches():
    module = _make_module()
    module._config_cache = {1: {"spam": {"enabled": True, "threshold": 5}}}
    module._cache_ttl = {1: 123.0}
    module._ruleset_cache = {1: [{"name": "ruleset"}]}
    module._ruleset_cache_ttl = {1: 123.0}

    # Base-class persist is a no-op on a bare module (no ctx wired).
    await module.save_dashboard_config(1, {"spam": {"enabled": True, "threshold": 3}})

    assert 1 not in module._config_cache, "flat config cache invalidated on save"
    assert 1 not in module._cache_ttl
    assert 1 not in module._ruleset_cache, "ruleset cache invalidated on save"
    assert 1 not in module._ruleset_cache_ttl


@pytest.mark.asyncio
async def test_save_dashboard_config_keeps_other_guilds_cached():
    module = _make_module()
    module._config_cache = {1: {"a": {}}, 2: {"b": {}}}
    module._cache_ttl = {1: 1.0, 2: 2.0}

    await module.save_dashboard_config(1, {"a": {}})

    assert 1 not in module._config_cache
    assert 2 in module._config_cache, "unrelated guild cache is preserved"
