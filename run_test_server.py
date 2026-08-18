"""Standalone Bark Dashboard test server with comprehensive mock bot."""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("BARK_BOT_TOKEN", "test_token_12345")
os.environ.setdefault("BARK_SECRET_KEY", "test_secret_key_abc_xyz_789")
os.environ.setdefault("BARK_DATABASE_URL", "sqlite+aiosqlite:////tmp/bark_test.db")
os.environ.setdefault("BARK_DATA_DIR", "/tmp/bark_test_data")
os.environ.setdefault("BARK_PUBLIC_URL", "http://127.0.0.1:8091")

sys.path.insert(0, str(Path(__file__).parent))
logging.basicConfig(level=logging.WARNING)

import discord
import uvicorn

from dashboard import create_app
from database import engine as db_engine
from database.engine import Base
from services.module_manager import ModuleManager


async def init_db():
    """Create all tables in memory."""
    engine = db_engine.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class MockGuild:
    """Fake guild object with all template-accessible attributes."""

    def __init__(self, id=123456789, name="Test Guild"):
        self.id = id
        self.name = name
        self.member_count = 142
        # Give the guild a real icon so the server-avatar-lg <img> path is
        # exercised (item 1). Use a real Discord CDN-style URL.
        self.icon = MagicMock()
        self.icon.url = "https://cdn.discordapp.com/icons/123456789/test_hash.png"
        self.premium_subscription_count = 5
        self.premium_tier = 2
        self.max_members = 200
        self.verification_level = MagicMock()
        self.verification_level.name = "Medium"
        self.created_at = datetime(2023, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        self.description = "A friendly test server for Bark's dashboard."
        self.banner = None
        self.features = ["ANIMATED_ICON", "NEWS"]

        # Discord scheduled events for the profile page. First event carries a
        # cover_image (Discord event banner) so the event-cover <img> renders.
        _ev_channel = MagicMock()
        _ev_channel.name = "General"
        _ev_cover = MagicMock()
        _ev_cover.url = "https://cdn.discordapp.com/events/501/test_cover.png"
        self.scheduled_events = [
            _mk_ev(id=501, name="Movie Night", description="Watch a movie together",
                   start_time=datetime(2026, 8, 20, 20, 0, tzinfo=timezone.utc), end_time=None,
                   status_name="scheduled", entity_name="voice",
                   url="https://discord.gg/events/501", user_count=8, channel=_ev_channel,
                   cover_image=_ev_cover),
            _mk_ev(id=502, name="Game Night", description=None,
                   start_time=datetime(2026, 8, 22, 19, 0, tzinfo=timezone.utc), end_time=None,
                   status_name="scheduled", entity_name="external",
                   url="https://discord.gg/events/502", user_count=12, channel=None,
                   cover_image=None),
        ]

        # Owner
        self.owner = MagicMock()
        self.owner.name = "TestOwner"
        self.owner.id = 98765
        self.owner_id = 98765

        # Channels
        self.text_channels = [MagicMock(spec=discord.TextChannel) for _ in range(10)]
        for i, c in enumerate(self.text_channels):
            c.name = f"channel-{i}"
            c.id = 1000 + i
            c.category = None
            c.position = i
            c.type = discord.ChannelType.text
        self.voice_channels = [MagicMock() for _ in range(5)]
        for i, c in enumerate(self.voice_channels):
            c.name = f"voice-{i}"
            c.id = 2000 + i
            c.category = None
            c.position = 10 + i
            c.type = discord.ChannelType.voice
        self.channels = [*self.text_channels, *self.voice_channels]
        self.emojis = []
        for i in range(8):
            e = MagicMock()
            e.name = f"emoji{i}"
            e.animated = False
            self.emojis.append(e)

        # Roles
        self.roles = [MagicMock() for _ in range(12)]
        role_colors = [0, 0, 0xE67E22, 0x3498DB, 0x9B59B6, 0x2ECC71, 0xE91E63, 0x1ABC9C, 0xF1C40F, 0x607D8B, 0x7289DA, 0x992D22]
        for i, r in enumerate(self.roles):
            r.name = f"Role {i}"
            r.id = 3000 + i
            r.position = i
            r.color = discord.Colour(role_colors[i])
            r.color.value = role_colors[i]
        self.roles[10].name = "Admin"
        self.roles[11].name = "Moderator"

        # Members (for guild.members iteration)
        self.members = []
        for i in range(20):
            m = MagicMock()
            m.id = 40000 + i
            m.name = f"User{i}"
            m.display_name = f"User{i}"
            m.discriminator = "0000"
            m.__str__.return_value = f"User{i}#0000"
            m.bot = i == 0
            m.top_role = self.roles[min(i, 11)]
            # roles[1:] excludes @everyone — give every member a couple of
            # coloured roles for the colour-coded role chips.
            m.roles = [self.roles[0]] + [self.roles[min(i + 1, 11)], self.roles[(i + 5) % 11 + 1]]
            m.voice = None
            m.timed_out_until = None
            m.is_timed_out.return_value = False
            m.joined_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
            m.created_at = datetime(2023, 1, 1, tzinfo=timezone.utc)
            m.avatar = None
            m.display_avatar = MagicMock()
            m.display_avatar.url = f"https://cdn.discordapp.com/avatars/{m.id}/hash.png"
            self.members.append(m)

        # For get_member
        self._member_dict = {m.id: m for m in self.members}

    def get_member(self, member_id):
        return self._member_dict.get(member_id)


def _mk_ev(**kwargs):
    """Build a mock ScheduledEvent. ``MagicMock(name=...)`` would set the
    reserved repr-name child mock instead of ``.name``, so set attributes
    explicitly after construction."""
    ev = MagicMock()
    ev.id = kwargs["id"]
    ev.name = kwargs["name"]
    ev.description = kwargs.get("description")
    ev.start_time = kwargs.get("start_time")
    ev.end_time = kwargs.get("end_time")
    _st = MagicMock()
    _st.name = kwargs.get("status_name", "scheduled")
    ev.status = _st
    _et = MagicMock()
    _et.name = kwargs.get("entity_name", "external")
    ev.entity_type = _et
    ev.url = kwargs.get("url")
    ev.user_count = kwargs.get("user_count", 0)
    ev.channel = kwargs.get("channel")
    ev.cover_image = kwargs.get("cover_image")
    return ev


class MockBarkBot:
    """Minimal BarkBot for testing the dashboard UI."""

    def __init__(self):
        self._module_manager = ModuleManager(self)
        self.user = MagicMock()
        self.user.name = "BarkBot"
        self.user.id = 123456789
        self.user.display_avatar = MagicMock()
        self.user.display_avatar.url = "https://cdn.discordapp.com/avatars/123/hash.png"
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._guild = MockGuild()
        self._module_manager.discover()
        self._server_events = {}  # seeded below with sample events

    @property
    def modules(self):
        return self._module_manager

    @property
    def guilds(self):
        return [self._guild]

    def is_ready(self):
        return True

    async def wait_until_ready(self):
        return None

    def get_guild(self, guild_id):
        if int(guild_id) == self._guild.id:
            return self._guild
        return None

    async def fetch_guild(self, guild_id):
        return self.get_guild(guild_id)

    async def fetch_channel(self, channel_id):
        return None

    # Server-events feed (mirrors BarkBot.record_server_event/recent_server_events).
    def record_server_event(self, guild_id, event_type, member, guild_name=None):
        self._server_events.setdefault(guild_id, []).insert(0, {
            "type": event_type,
            "user_id": str(getattr(member, "id", "")),
            "user_name": getattr(member, "display_name", None) or str(member),
            "tag": str(member),
            "avatar_url": None,
            "guild_name": guild_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        del self._server_events[guild_id][30:]

    def recent_server_events(self, guild_id, limit=25):
        return self._server_events.get(guild_id, [])[:limit]

    def record_message(self, guild_id, channel):
        pass

    def record_reaction(self, guild_id, emoji):
        pass

    def message_stats(self, guild_id):
        from datetime import date
        return {
            "date": date.today().isoformat(),
            "messages": 42,
            "channels": {
                "1000": {"name": "channel-0", "count": 20},
                "1001": {"name": "channel-1", "count": 12},
                "1002": {"name": "channel-2", "count": 6},
            },
            "emojis": {"laugh": 30, "wow": 8, "🔥": 5},
        }


# Also inject a mock into bot.client for any direct imports
import bot.client

original_barkbot = bot.client.BarkBot
bot.client.BarkBot = MockBarkBot  # type: ignore

bot = MockBarkBot()

# Seed sample server events + member-growth snapshots for visual verification.
from datetime import date, timedelta
from types import SimpleNamespace

bot.record_server_event(bot._guild.id, "member_join", SimpleNamespace(id=90001, display_name="Newbie", tag="Newbie#1"), bot._guild.name)
bot.record_server_event(bot._guild.id, "member_leave", SimpleNamespace(id=90002, display_name="Quitter", tag="Quitter#1"), bot._guild.name)
bot.record_server_event(bot._guild.id, "member_join", SimpleNamespace(id=90003, display_name="Fresh", tag="Fresh#1"), bot._guild.name)

# Initialize DB tables
loop = bot.loop
loop.run_until_complete(init_db())

# Seed ~14 days of member growth so the line chart renders.
from database.engine import session_scope
from database.models.analytics import ActivitySnapshot
from database.models.guild import Guild


def seed_growth():
    async def _run():
        from sqlalchemy import select

        async with session_scope() as s:
            existing = await s.execute(select(Guild).where(Guild.discord_id == str(bot._guild.id)))
            if not existing.scalars().first():
                s.add(Guild(discord_id=str(bot._guild.id), name=bot._guild.name))
                await s.commit()
        async with session_scope() as s:
            start = 128
            from database.models.analytics import DailyChannelStat, DailyEmojiStat

            # Per-day channel/emoji stats — the source of truth for Statistics.
            for d in range(14):
                s.add(ActivitySnapshot(
                    guild_id=str(bot._guild.id),
                    snapshot_date=date.today() - timedelta(days=13 - d),
                    total_members=start + d * 2,
                    total_channels=40 + d,
                ))
            for d in range(14):
                s.add(DailyChannelStat(
                    guild_id=str(bot._guild.id),
                    stat_date=date.today() - timedelta(days=13 - d),
                    channel_id="1000", channel_name="channel-0", message_count=20,
                ))
                s.add(DailyChannelStat(
                    guild_id=str(bot._guild.id),
                    stat_date=date.today() - timedelta(days=13 - d),
                    channel_id="1001", channel_name="channel-1", message_count=12,
                ))
                s.add(DailyChannelStat(
                    guild_id=str(bot._guild.id),
                    stat_date=date.today() - timedelta(days=13 - d),
                    channel_id="1002", channel_name="channel-2", message_count=6,
                ))
                s.add(DailyEmojiStat(
                    guild_id=str(bot._guild.id),
                    stat_date=date.today() - timedelta(days=13 - d),
                    emoji_name="laugh", count=30,
                ))
                s.add(DailyEmojiStat(
                    guild_id=str(bot._guild.id),
                    stat_date=date.today() - timedelta(days=13 - d),
                    emoji_name="wow", count=8,
                ))
                s.add(DailyEmojiStat(
                    guild_id=str(bot._guild.id),
                    stat_date=date.today() - timedelta(days=13 - d),
                    emoji_name="🔥", count=5,
                ))
            # Grant user 42 manage access so the guild gate lets the browser in.
            from database.models.permissions import DashboardUser
            from services.dashboard_access import replace_user_guild_access

            if not (await s.execute(select(DashboardUser).where(DashboardUser.discord_id == "42"))).scalars().first():
                s.add(DashboardUser(discord_id="42", username="Tester", role="admin"))
                await s.flush()
            from database.models.guild import GuildSetting

            if not (await s.execute(select(GuildSetting).where(GuildSetting.guild_id == str(bot._guild.id), GuildSetting.key == "motd"))).scalars().first():
                s.add(GuildSetting(guild_id=str(bot._guild.id), key="motd", value="Welcome to the Test Guild! 👋 Check the events below."))
            await replace_user_guild_access(
                s,
                "42",
                [{"id": str(bot._guild.id), "name": bot._guild.name, "permissions": str(0x20), "owner": True}],
            )
    loop.run_until_complete(_run())


seed_growth()

# Force permissive mode (no OAuth auth) so the browser can view guild pages
# without forging a signed session cookie during visual verification.
import config as bark_config

bark_config.config.oauth2.client_id = ""
bark_config.config.oauth2.client_secret = ""
bark_config.config.oauth2.redirect_uri = ""


def seed_moderation():
    """Seed rulesets, cases, warnings, notes, word lists, audit logs so the
    data tabs render real content during visual verification."""

    async def _run():
        from sqlalchemy import select

        from database.models.moderation import AuditLog, ModerationCase, UserNote, Warning
        from database.models.ruleset import Rule, RuleSet, WordList

        async with session_scope() as s:
            if (await s.execute(select(RuleSet).where(RuleSet.guild_id == str(bot._guild.id)))).scalars().first():
                return
            rs = RuleSet(guild_id=str(bot._guild.id), name="Scam Protection", enabled=True, priority=100)
            rs2 = RuleSet(guild_id=str(bot._guild.id), name="New Account Shield", enabled=False, priority=50,
                          account_age_minutes_max=2880)
            s.add(rs)
            s.add(rs2)
            await s.flush()
            s.add(Rule(ruleset_id=rs.id, trigger_type="scam_link", effect_type="ban",
                       trigger_config="{}", effect_config="{\"delete_days\": 1}", conditions="{}"))
            s.add(Rule(ruleset_id=rs.id, trigger_type="invite_link", effect_type="warn",
                       trigger_config="{\"threshold\": 1, \"window_seconds\": 10}", effect_config="{}", conditions="{}"))
            s.add(Rule(ruleset_id=rs2.id, trigger_type="any_link", effect_type="warn",
                       trigger_config="{\"threshold\": 1}", effect_config="{}", conditions="{}"))
            s.add(WordList(guild_id=str(bot._guild.id), name="Swear words", list_type="word", entries='["badword1", "badword2"]'))
            s.add(WordList(guild_id=str(bot._guild.id), name="Scam domains", list_type="domain", entries='["scam.gg", "evil.io"]'))
            s.add(ModerationCase(guild_id=str(bot._guild.id), case_number=1, action_type="warn", target_id="90001",
                                 target_tag="User0#0000", moderator_id="42", moderator_tag="Tester#0000",
                                 reason="Repeated spam in #general", resolved=False))
            s.add(ModerationCase(guild_id=str(bot._guild.id), case_number=2, action_type="ban", target_id="90002",
                                 target_tag="User1#0000", moderator_id="42", moderator_tag="Tester#0000",
                                 reason="Raid participation / malicious link", resolved=True))
            s.add(Warning(guild_id=str(bot._guild.id), user_id="90001", moderator_id="42", reason="Spam", active=True))
            s.add(UserNote(guild_id=str(bot._guild.id), user_id="90001", author_id="42",
                           content="Repeat offender — keep an eye on them.", created_at=datetime.now(timezone.utc)))
            for action in ("warn", "ban", "member_join", "message_delete", "voice_join"):
                s.add(AuditLog(guild_id=str(bot._guild.id), action=action, actor_id="42", target_id="90001",
                               details="{\"channel\": \"#general\"}",
                               created_at=datetime.now(timezone.utc)))
            await s.flush()
            await s.commit()

    loop.run_until_complete(_run())


seed_moderation()


def seed_stats():
    """Seed reputation events, voice sessions, and voice game stats over several
    days so the new Statistics charts render real content during verification."""

    async def _run():
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import select

        from database.models.analytics import VoiceGameStat
        from database.models.reputation import ReputationEvent
        from database.models.voice import VoiceSession

        async with session_scope() as s:
            if (await s.execute(select(ReputationEvent).where(ReputationEvent.guild_id == str(bot._guild.id)))).scalars().first():
                return
            now = datetime.now(timezone.utc)
            for d in range(14):
                day = now - timedelta(days=13 - d)
                for _ in range(4):
                    s.add(ReputationEvent(
                        guild_id=str(bot._guild.id), actor_id="42", target_id="90001",
                        event_type="message", points=1, channel_id="1000",
                        created_at=day + timedelta(hours=12),
                    ))
                s.add(ReputationEvent(
                    guild_id=str(bot._guild.id), actor_id="42", target_id="90002",
                    event_type="thanks", points=3, created_at=day + timedelta(hours=13),
                ))
                s.add(VoiceGameStat(
                    guild_id=str(bot._guild.id), game_name="Valorant",
                    recorded_at=day + timedelta(hours=15),
                ))
                if d % 2 == 0:
                    s.add(VoiceGameStat(
                        guild_id=str(bot._guild.id), game_name="Minecraft",
                        recorded_at=day + timedelta(hours=16),
                    ))
                s.add(VoiceSession(
                    guild_id=str(bot._guild.id), user_id="90001", user_tag="User0#0000",
                    channel_id="1000", channel_name="Gaming", joined_at=day + timedelta(hours=15),
                    left_at=day + timedelta(hours=16, minutes=30), duration_seconds=5400,
                ))
            await s.commit()

    loop.run_until_complete(_run())


seed_stats()

dashboard_app = create_app(bot)  # type: ignore
app = dashboard_app.app

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8091
    print(f"🚀 Bark test dashboard starting on http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
