"""Engine configuration from environment variables.

Read fresh per call (no caching) so tests can monkeypatch ``os.environ``.
Construction is cheap; per-request ``os.getenv`` is fine at this scale.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

ENGINE_VERSION = "0.1.0"


@dataclass(frozen=True)
class EngineConfig:
    engine_token: str = field(default_factory=lambda: os.getenv("BARK_MEDIA_ENGINE_TOKEN", ""))
    ai_model: str = field(default_factory=lambda: os.getenv("BARK_MEDIA_AI_MODEL", "gpt-5.6-sol"))
    openai_api_key: str = field(default_factory=lambda: os.getenv("BARK_MEDIA_OPENAI_API_KEY", ""))
    data_dir: str = field(
        default_factory=lambda: os.getenv(
            "BARK_MEDIA_DATA_DIR", os.path.expanduser("~/Projects/bark-media-engine/data")
        )
    )
    media_db_path: str = field(default_factory=lambda: os.getenv("BARK_MEDIA_DB_PATH", ""))
    port: int = field(default_factory=lambda: int(os.getenv("BARK_MEDIA_PORT", "8094")))
    max_concurrency: int = field(default_factory=lambda: int(os.getenv("BARK_MEDIA_MAX_CONCURRENCY", "2")))
    cache_max_bytes: int = field(
        default_factory=lambda: int(os.getenv("BARK_MEDIA_CACHE_MAX_BYTES", str(1024**3)))
    )
    job_timeout_s: int = field(default_factory=lambda: int(os.getenv("BARK_MEDIA_JOB_TIMEOUT_S", "60")))

    @property
    def version(self) -> str:
        return ENGINE_VERSION


def get_config() -> EngineConfig:
    return EngineConfig()
