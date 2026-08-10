"""Engine configuration: environment overrides, bark-instance defaults.

Read fresh per call (no caching) so tests can monkeypatch ``os.environ``.
Unset ``BARK_MEDIA_*`` values fall back to the instance's bark config
(data dir / db / version) — the engine IS bark core, so it should agree
with the bot it renders for.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_FALLBACK_VERSION = "0.0.0"


def _bark_data_dir() -> Path:
    """The instance data dir from bark's config singleton (lazy, safe)."""
    try:
        import config as _cfg  # noqa: PLC0415 — bark core, same repo/env
        return Path(_cfg.config.data_dir)
    except Exception:
        return Path("data").resolve()


def _bark_version() -> str:
    try:
        import bark_version  # noqa: PLC0415
        return bark_version.__version__
    except Exception:
        return _FALLBACK_VERSION


@dataclass(frozen=True)
class EngineConfig:
    engine_token: str = field(default_factory=lambda: os.getenv("BARK_MEDIA_ENGINE_TOKEN", ""))
    ai_model: str = field(default_factory=lambda: os.getenv("BARK_MEDIA_AI_MODEL", "gpt-5.6-sol"))
    openai_api_key: str = field(default_factory=lambda: os.getenv("BARK_MEDIA_OPENAI_API_KEY", ""))
    data_dir: Path = field(default_factory=lambda: Path(
        os.getenv("BARK_MEDIA_DATA_DIR", str(_bark_data_dir() / "media"))
    ))
    media_db_path: str = field(default_factory=lambda: os.getenv(
        "BARK_MEDIA_DB_PATH", str(_bark_data_dir() / "bark.db")
    ))
    port: int = field(default_factory=lambda: int(os.getenv("BARK_MEDIA_PORT", "8094")))
    max_concurrency: int = field(
        default_factory=lambda: int(os.getenv("BARK_MEDIA_MAX_CONCURRENCY", "2"))
    )
    cache_max_bytes: int = field(
        default_factory=lambda: int(os.getenv("BARK_MEDIA_CACHE_MAX_BYTES", str(1024**3)))
    )
    job_timeout_s: int = field(
        default_factory=lambda: int(os.getenv("BARK_MEDIA_JOB_TIMEOUT_S", "60"))
    )

    @property
    def version(self) -> str:
        return _bark_version()


def get_config() -> EngineConfig:
    return EngineConfig()
