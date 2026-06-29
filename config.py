"""
Bark configuration loader.

Priority:
1. Environment variables
2. config.yaml (optional)
3. Defaults
"""

import os
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BotConfig:
    token: str = ""
    command_prefix: str = "!"
    sync_commands: bool = True
    intents: int = 0  # Default: 0 (all intents via defaults)
    activity_type: str = "playing"
    activity_text: str = "with the dashboard"


@dataclass
class DashboardConfig:
    host: str = "127.0.0.1"
    port: int = 8090
    secret_key: str = "bark-dev-secret-change-in-production"
    session_ttl: int = 86400  # 24 hours
    cors_origins: list[str] = field(default_factory=lambda: ["*"])


@dataclass
class DatabaseConfig:
    url: str = "sqlite+aiosqlite:///bark.db"
    echo: bool = False
    pool_size: int = 5
    max_overflow: int = 10


@dataclass
class LoggingConfig:
    level: str = "INFO"
    format: str = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"


@dataclass
class Config:
    bot: BotConfig = field(default_factory=BotConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    data_dir: Path = field(default_factory=lambda: Path("data"))

    def __post_init__(self):
        self.data_dir = Path(self.data_dir).resolve()

    @classmethod
    def load(cls) -> "Config":
        """Load config from environment variables with sensible defaults."""
        cfg = cls()

        # Bot
        cfg.bot.token = os.getenv("BARK_BOT_TOKEN", "")
        cfg.bot.command_prefix = os.getenv("BARK_COMMAND_PREFIX", "!")
        cfg.bot.sync_commands = os.getenv("BARK_SYNC_COMMANDS", "true").lower() == "true"

        # Dashboard
        cfg.dashboard.host = os.getenv("BARK_DASHBOARD_HOST", "127.0.0.1")
        try:
            cfg.dashboard.port = int(os.getenv("BARK_DASHBOARD_PORT", "8090"))
        except ValueError:
            cfg.dashboard.port = 8090
        cfg.dashboard.secret_key = os.getenv("BARK_SECRET_KEY", "bark-dev-secret-change-in-production")

        # Database
        cfg.database.url = os.getenv("BARK_DATABASE_URL", "sqlite+aiosqlite:///bark.db")
        cfg.database.echo = os.getenv("BARK_DATABASE_ECHO", "false").lower() == "true"

        # Logging
        cfg.logging.level = os.getenv("BARK_LOG_LEVEL", "INFO").upper()

        # Data directory
        data_dir = os.getenv("BARK_DATA_DIR", "data")
        cfg.data_dir = Path(data_dir).resolve()

        # Ensure data directory exists
        cfg.data_dir.mkdir(parents=True, exist_ok=True)

        return cfg


config = Config.load()
