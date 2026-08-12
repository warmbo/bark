"""
Bark configuration loader.

Priority:
1. Environment variables
2. config.yaml (optional)
3. Defaults
"""

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when Bark configuration is missing or invalid."""


@dataclass
class BotConfig:
    token: str = ""
    command_prefix: str = "!"
    sync_commands: bool = True
    sync_guild_id: int | None = None  # if set, sync slash commands to this guild only (instant, no global cache)
    activity_text: str = "with the dashboard"


@dataclass
class DashboardConfig:
    host: str = "127.0.0.1"
    port: int = 8090
    public_url: str = "http://127.0.0.1:8090"
    secret_key: str = ""
    session_ttl: int = 2592000  # 30 days — signed session cookie lifetime
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    force_https: bool = False
    # Comma-separated IPs/CIDRs allowed to set X-Forwarded-* headers (used for
    # the real client IP and the https scheme when behind a TLS-terminating
    # proxy like Cloudflare). Default "127.0.0.1" covers a same-host reverse
    # proxy / Cloudflare Tunnel (cloudflared connects to loopback). Set to "*"
    # (or Cloudflare's edge ranges) when Cloudflare connects directly to the
    # origin, and firewall the origin to Cloudflare so clients can't spoof the
    # headers.
    forwarded_allow_ips: str = "127.0.0.1"
    rate_limit_per_minute: int = 60
    invite_url: str = ""

    @property
    def secure_cookies(self) -> bool:
        return self.force_https or self.public_url.startswith("https://")


@dataclass
class DatabaseConfig:
    url: str = "sqlite+aiosqlite:///bark.db"
    echo: bool = False
    pool_size: int = 5
    max_overflow: int = 10


@dataclass
class InstanceConfig:
    """Self-update settings — the instance's git checkout + systemd unit."""

    repo_dir: str = ""  # empty = auto-detect from the package location
    service_name: str = "bark"  # systemd unit name (used for the restart hint)
    update_branch: str = "main"  # default channel: stable (main) or dev
    update_remote: str = "github"  # primary git remote to fetch updates from
    stable_branch: str = "main"  # stable-channel branch; empty = remote default
    dev_badge: bool = False  # show the DEV VERSION watermark everywhere


@dataclass
class OAuth2Config:
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    owner_discord_ids: set[str] = field(default_factory=set)

    @property
    def enabled(self) -> bool:
        """OAuth is usable only when the complete Discord flow is configured."""
        return bool(self.client_id and self.client_secret and self.redirect_uri)


@dataclass
class LoggingConfig:
    level: str = "INFO"
    format: str = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"


def _get_or_generate_secret_key(data_dir: Path) -> str:
    """Return a saved secret key, or generate and persist one."""
    key_file = data_dir / ".secret_key"
    if key_file.exists():
        key_file.chmod(0o600)
        return key_file.read_text().strip()
    key = secrets.token_hex(32)
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        key_file.chmod(0o600)
        return key_file.read_text().strip()
    with os.fdopen(descriptor, "w") as handle:
        handle.write(key)
    return key


@dataclass
class Config:
    bot: BotConfig = field(default_factory=BotConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    instance: InstanceConfig = field(default_factory=InstanceConfig)
    oauth2: OAuth2Config = field(default_factory=OAuth2Config)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    data_dir: Path = field(default_factory=lambda: Path("data"))

    def __post_init__(self):
        self.data_dir = Path(self.data_dir).resolve()

    @property
    def needs_setup(self) -> bool:
        """True when Bark has no Discord credentials yet — first-run setup.

        The app boots a minimal setup server (no bot) that writes ``.env``
        from the dashboard instead of requiring hand-edited configuration.
        """
        return not self.bot.token

    def validate_startup(self) -> None:
        """Validate settings required to start the complete Bark process."""
        if not self.bot.token:
            raise ConfigurationError(
                "BARK_BOT_TOKEN is required (or provide a private .token file)"
            )
        oauth_credentials = (
            self.oauth2.client_id,
            self.oauth2.client_secret,
        )
        if any(oauth_credentials) and (not all(oauth_credentials) or not self.oauth2.redirect_uri):
            raise ConfigurationError(
                "Discord OAuth requires BARK_OAUTH2_CLIENT_ID, "
                "BARK_OAUTH2_CLIENT_SECRET, and BARK_OAUTH2_REDIRECT_URI"
            )
        if self.dashboard.host not in {"127.0.0.1", "::1", "localhost"} and not self.oauth2.enabled:
            raise ConfigurationError(
                "Discord OAuth must be configured before exposing the dashboard "
                "on a non-loopback BARK_DASHBOARD_HOST"
            )
        # Ports < 1024 are privileged: non-root users (Android/Termux, unprivileged
        # containers, normal desktops) can't bind them. Fail with a clear message
        # instead of a cryptic "Permission denied" at bind time.
        if (
            self.dashboard.port < 1024
            and hasattr(os, "geteuid")
            and os.geteuid() != 0
        ):
            raise ConfigurationError(
                f"BARK_DASHBOARD_PORT={self.dashboard.port} is below 1024 — non-root "
                "users cannot bind privileged ports. Set BARK_DASHBOARD_PORT to 1024 "
                "or higher (e.g. 8090), or run Bark as root."
            )
        if self.oauth2.enabled and not self.oauth2.owner_discord_ids:
            raise ConfigurationError(
                "BARK_OWNER_DISCORD_IDS is required when Discord OAuth is enabled"
            )

    @classmethod
    def load(cls) -> "Config":
        """Load config from environment variables with sensible defaults."""
        cfg = cls()

        # Data directory — must resolve early for secret key
        data_dir = os.getenv("BARK_DATA_DIR", "data")
        cfg.data_dir = Path(data_dir).resolve()
        cfg.data_dir.mkdir(parents=True, exist_ok=True)

        # Bot — env var takes priority, then .token file
        cfg.bot.token = os.getenv("BARK_BOT_TOKEN", "")
        if not cfg.bot.token:
            token_path = cfg.data_dir.parent / ".token"
            if token_path.exists():
                cfg.bot.token = token_path.read_text().strip()
            else:
                token_path = Path(".token")
                if token_path.exists():
                    cfg.bot.token = token_path.read_text().strip()
        cfg.bot.command_prefix = os.getenv("BARK_COMMAND_PREFIX", "!")
        cfg.bot.sync_commands = os.getenv("BARK_SYNC_COMMANDS", "true").lower() == "true"
        raw_sync_guild = os.getenv("BARK_SYNC_GUILD_ID", "")
        try:
            cfg.bot.sync_guild_id = int(raw_sync_guild) if raw_sync_guild else None
        except ValueError:
            cfg.bot.sync_guild_id = None

        # Dashboard
        cfg.dashboard.host = os.getenv("BARK_DASHBOARD_HOST", cfg.dashboard.host)
        raw_port = os.getenv("BARK_DASHBOARD_PORT", "8090")
        try:
            cfg.dashboard.port = int(raw_port)
        except ValueError as exc:
            raise ConfigurationError(
                f"BARK_DASHBOARD_PORT must be an integer, got {raw_port!r}"
            ) from exc
        if not 1 <= cfg.dashboard.port <= 65535:
            raise ConfigurationError("BARK_DASHBOARD_PORT must be between 1 and 65535")
        cfg.dashboard.force_https = os.getenv("BARK_FORCE_HTTPS", "false").lower() == "true"
        cfg.dashboard.forwarded_allow_ips = os.getenv(
            "BARK_FORWARDED_ALLOW_IPS", "127.0.0.1"
        )
        cfg.dashboard.public_url = os.getenv("BARK_PUBLIC_URL", cfg.dashboard.public_url).rstrip(
            "/"
        )
        raw_session_ttl = os.getenv("BARK_DASHBOARD_SESSION_TTL", "")
        try:
            cfg.dashboard.session_ttl = int(raw_session_ttl) if raw_session_ttl else cfg.dashboard.session_ttl
        except ValueError:
            raise ConfigurationError(
                f"BARK_DASHBOARD_SESSION_TTL must be an integer number of seconds, got {raw_session_ttl!r}"
            ) from None
        env_key = os.getenv("BARK_SECRET_KEY", "")
        cfg.dashboard.secret_key = env_key or _get_or_generate_secret_key(cfg.data_dir)

        # Database
        cfg.database.url = os.getenv("BARK_DATABASE_URL", "sqlite+aiosqlite:///bark.db")
        cfg.database.echo = os.getenv("BARK_DATABASE_ECHO", "false").lower() == "true"

        # Logging
        cfg.logging.level = os.getenv("BARK_LOG_LEVEL", "INFO").upper()

        # OAuth2
        cfg.oauth2.client_id = os.getenv("BARK_OAUTH2_CLIENT_ID", "")
        cfg.oauth2.client_secret = os.getenv("BARK_OAUTH2_CLIENT_SECRET", "")
        cfg.oauth2.redirect_uri = os.getenv(
            "BARK_OAUTH2_REDIRECT_URI",
            f"{cfg.dashboard.public_url}/auth/callback",
        )
        cfg.oauth2.owner_discord_ids = {
            value.strip()
            for value in os.getenv("BARK_OWNER_DISCORD_IDS", "").split(",")
            if value.strip()
        }

        # Invite URL
        cfg.dashboard.invite_url = os.getenv("BARK_INVITE_URL", "")

        # Self-update
        cfg.instance.repo_dir = os.getenv("BARK_REPO_DIR", "")
        cfg.instance.service_name = os.getenv("BARK_SERVICE_NAME", "bark")
        cfg.instance.update_branch = os.getenv("BARK_UPDATE_BRANCH", "main")
        cfg.instance.update_remote = os.getenv("BARK_UPDATE_REMOTE", "github")
        cfg.instance.stable_branch = os.getenv("BARK_STABLE_BRANCH", "main")
        cfg.instance.dev_badge = os.getenv("BARK_DEV_BADGE", "false").lower() == "true"

        return cfg


config = Config.load()
