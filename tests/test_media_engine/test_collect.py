"""Payload collectors — bark-shaped tables seeded into a tmp SQLite."""

import sqlite3
from datetime import date, timedelta

import pytest

from services.media_engine.collect import (
    build_leaderboard_payload,
    build_profile_payload,
    get_activity_bars,
    get_favorite_channels,
)
from services.media_engine.db import connect_readonly


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "bark.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE reputation_profiles (
            guild_id TEXT, user_id TEXT, total_score REAL, level INTEGER,
            current_tier TEXT, weekly_score REAL, monthly_score REAL,
            thanks_received INTEGER, messages_count INTEGER,
            reactions_received INTEGER, voice_minutes INTEGER,
            last_activity TEXT, week_start TEXT, month_start TEXT
        );
        CREATE TABLE reputation_tiers (
            guild_id TEXT, name TEXT, symbol TEXT, min_score REAL,
            color_hex TEXT, is_default INTEGER, sort_order INTEGER
        );
        CREATE TABLE reputation_rewards (
            id INTEGER PRIMARY KEY, guild_id TEXT, name TEXT, description TEXT,
            reward_type TEXT, reward_value TEXT, required_tier TEXT,
            required_level INTEGER, auto_award INTEGER
        );
        CREATE TABLE reputation_awards (
            guild_id TEXT, user_id TEXT, reward_id INTEGER, tier_name TEXT,
            level_at_award INTEGER, score_at_award REAL, created_at TEXT
        );
        CREATE TABLE reputation_events (
            guild_id TEXT, actor_id TEXT, target_id TEXT, event_type TEXT,
            points REAL, message_id TEXT, channel_id TEXT, emoji TEXT,
            created_at TEXT
        );
        """
    )
    today = date(2026, 8, 10)
    # target user: 3 days ago → 2 events, yesterday → 1 event, today → 1 event
    events = [
        ("g1", "u1", "c1", "message", today - timedelta(days=3)),
        ("g1", "u1", "c1", "reaction", today - timedelta(days=3)),
        ("g1", "u1", "c2", "message", today - timedelta(days=1)),
        ("g1", "u1", "c2", "message", today),
        ("g1", "u2", "c1", "message", today),  # other actor — ignored
        ("g2", "u1", "c9", "message", today),  # other guild — ignored
    ]
    for guild, actor, channel, etype, when in events:
        conn.execute(
            "INSERT INTO reputation_events (guild_id, actor_id, channel_id, event_type, points, created_at) "
            "VALUES (?, ?, ?, ?, 1.0, ?)",
            (guild, actor, channel, etype, when.isoformat()),
        )
    conn.execute(
        "INSERT INTO reputation_profiles VALUES "
        "('g1','u1',1240.5,12,'Legend',40.2,210.0,84,4210,930,1820,'2026-08-09 18:00:00','2026-08-03','2026-07-11'),"
        "('g1','u2',900.0,9,'Veteran',10.0,60.0,20,1200,300,500,'2026-08-08 10:00:00','2026-08-03','2026-07-11')"
    )
    conn.execute(
        "INSERT INTO reputation_tiers VALUES "
        "('g1','Legend','👑',1000.0,'#ffb020',0,3),"
        "('g1','Veteran','⚔️',500.0,'#a78bfa',0,2),"
        "('g1','unranked','',0.0,'#99aab5',1,1)"
    )
    conn.execute(
        "INSERT INTO reputation_rewards VALUES "
        "(1,'g1','Early Member','Joined in the first week','badge','early','unranked',0,1),"
        "(2,'g1','Voice Hero','500+ voice minutes','badge','voice','Veteran',0,1)"
    )
    conn.execute(
        "INSERT INTO reputation_awards VALUES "
        "('g1','u1',1,'unranked',2,150.0,'2026-01-05 10:00:00'),"
        "('g1','u1',2,'Veteran',9,510.0,'2026-03-20 12:00:00')"
    )
    conn.commit()
    conn.close()
    return str(path)


def test_build_profile_payload_full(db_path):
    engine = connect_readonly(db_path)
    payload = build_profile_payload(
        engine, "g1", "u1",
        user={"display_name": "Cody", "username": "cody", "avatar_url": "https://cdn.example/a.png",
              "presence": "online"},
        roles=[{"name": "Mod", "color": 0x5865F2, "hoist": True}],
        today=date(2026, 8, 10),
    )
    assert payload["user"]["display_name"] == "Cody"
    assert payload["user"]["id"] == "u1"
    assert payload["roles"] == [{"name": "Mod", "color": 0x5865F2, "hoist": True}]
    rep = payload["reputation"]
    assert rep["score"] == 1240.5
    assert rep["level"] == 12
    assert rep["tier"] == "Legend"
    assert rep["tier_symbol"] == "👑"
    assert rep["tier_color"] == "#ffb020"
    assert rep["voice_minutes"] == 1820
    assert payload["badges"] == [
        {"name": "Voice Hero", "description": "500+ voice minutes", "icon": ""},
        {"name": "Early Member", "description": "Joined in the first week", "icon": ""},
    ]
    favs = payload["favorites"]
    assert favs[0]["channel_id"] == "c1" and favs[0]["count"] == 2
    assert favs[1]["channel_id"] == "c2" and favs[1]["count"] == 2
    assert payload["activity"]["bars_weekly"] == [0, 0, 0, 2, 0, 1, 1]
    # monthly buckets (newest week = Aug 4..10 holds all 4 events)
    assert payload["activity"]["bars_monthly"] == [0, 0, 0, 4]


def test_activity_bars_exact(db_path):
    engine = connect_readonly(db_path)
    bars = get_activity_bars(engine, "g1", "u1", today=date(2026, 8, 10))
    # days Aug 4..Aug 10: 4th=0,5th=0,6th=0,7th=2 (Aug 7 = 3 days ago),8th=0,9th=1,10th=1
    assert bars["bars_weekly"] == [0, 0, 0, 2, 0, 1, 1]
    assert sum(bars["bars_monthly"]) == 4


def test_build_profile_payload_missing_user(db_path):
    engine = connect_readonly(db_path)
    payload = build_profile_payload(engine, "g1", "ghost", today=date(2026, 8, 10))
    assert payload["user"]["id"] == "ghost"
    assert payload["user"]["display_name"] == "ghost"
    assert payload["reputation"] == {}
    assert payload["badges"] == []
    assert payload["favorites"] == []
    assert payload["activity"]["bars_weekly"] == [0] * 7


def test_favorites_ignore_other_actor_and_guild(db_path):
    engine = connect_readonly(db_path)
    favs = get_favorite_channels(engine, "g1", "u2")
    assert favs == [{"channel_id": "c1", "name": None, "count": 1}]


def test_leaderboard_ordering(db_path):
    engine = connect_readonly(db_path)
    board = build_leaderboard_payload(engine, "g1", limit=10)
    assert [row["rank"] for row in board] == [1, 2]
    assert board[0]["user_id"] == "u1" and board[0]["score"] == 1240.5
    assert board[1]["tier"] == "Veteran"


def test_degenerate_tier_curve_hides_next_tier(db_path):
    """Equal min_scores (e.g. all tiers at 0.0) → no meaningless 4/0 label."""
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO reputation_tiers VALUES "
                 "('g1','Flat1','',0.0,'#111111',0,1),('g1','Flat2','',0.0,'#222222',0,2)")
    conn.execute("INSERT INTO reputation_profiles VALUES "
                 "('g1','u3',7.0,1,'Flat1',0.0,0.0,0,7,0,0,NULL,'2026-08-03','2026-07-11')")
    conn.commit()
    conn.close()

    engine = connect_readonly(db_path)
    payload = build_profile_payload(engine, "g1", "u3", today=date(2026, 8, 10))
    rep = payload["reputation"]
    assert rep["tier"] == "Flat1"
    assert rep["next_tier"] is None
    assert rep["tier_progress"] == 0.0


def test_missing_db_returns_defaults(tmp_path):
    engine = connect_readonly(str(tmp_path / "nope.db"))
    payload = build_profile_payload(engine, "g1", "u1", today=date(2026, 8, 10))
    # missing file must not raise — collectors degrade to defaults
    assert payload["reputation"] == {}
    assert payload["badges"] == []
    assert build_leaderboard_payload(engine, "g1") == []
