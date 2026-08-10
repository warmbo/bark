"""End-to-end render API: auth, job lifecycle, cache hit, theme list."""

import asyncio
from pathlib import Path

import httpx
import pytest
from PIL import Image

from services.media_engine.main import app

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

PAYLOAD = {
    "user": {"id": "1", "display_name": "Cody", "username": "cody",
             "presence": "online", "joined_at": "2024-01-05T00:00:00Z"},
    "roles": [],
    "reputation": {"score": 1240.5, "level": 12, "tier": "Legend",
                   "tier_color": "#3b82f6", "tier_progress": 0.62,
                   "messages": 4210, "reactions": 930, "thanks": 84,
                   "voice_minutes": 1820},
    "activity": {"bars_weekly": [3, 5, 2, 8, 6, 4, 7]},
    "badges": [{"name": "Early", "description": "", "icon": ""}],
    "favorites": [{"channel_id": "1", "name": "general", "count": 320}],
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BARK_MEDIA_ENGINE_TOKEN", TOKEN)
    monkeypatch.setenv("BARK_MEDIA_DATA_DIR", str(tmp_path))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_render_requires_auth(client):
    r = await client.post("/v1/render", json={"kind": "profile"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_unknown_kind_and_output(client):
    r = await client.post("/v1/render", json={"kind": "nope"}, headers=AUTH)
    assert r.status_code == 400
    r = await client.post("/v1/render", json={"kind": "profile", "output": "webm"}, headers=AUTH)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_unknown_job_404(client):
    r = await client.get("/v1/jobs/does-not-exist", headers=AUTH)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_full_render_lifecycle(client):
    r = await client.post("/v1/render", json={
        "kind": "profile", "guild_id": "g1", "user_id": "u1", "payload": PAYLOAD,
    }, headers=AUTH)
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    for _ in range(100):
        jr = await client.get(f"/v1/jobs/{job_id}", headers=AUTH)
        status = jr.json()["status"]
        if status in ("done", "error"):
            break
        await asyncio.sleep(0.05)
    assert jr.json()["status"] == "done", jr.json()

    path = Path(jr.json()["file"])
    assert path.is_file()
    img = Image.open(path)
    assert img.size == (1024, 1792)


@pytest.mark.asyncio
async def test_cache_hit_returns_same_file(client):
    def post():
        return client.post("/v1/render", json={
            "kind": "profile", "guild_id": "g1", "user_id": "u1", "payload": PAYLOAD,
        }, headers=AUTH)

    async def poll(job_id):
        for _ in range(100):
            jr = await client.get(f"/v1/jobs/{job_id}", headers=AUTH)
            if jr.json()["status"] in ("done", "error"):
                return jr.json()
            await asyncio.sleep(0.05)
        raise TimeoutError("job did not finish")

    first = await poll((await post()).json()["job_id"])
    second = await poll((await post()).json()["job_id"])
    assert first["status"] == second["status"] == "done"
    assert first["file"] == second["file"]  # cache key stable → same artifact


@pytest.mark.asyncio
async def test_theme_list(client):
    r = await client.get("/v1/theme", headers=AUTH)
    assert r.status_code == 200
    names = [t["name"] for t in r.json()["themes"]]
    assert names == ["bark"]


def _seed_db(path: Path) -> None:
    import sqlite3

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
        INSERT INTO reputation_profiles VALUES
        ('g1','u1',500.0,8,'Veteran',10.0,60.0,20,1200,300,500,
         '2026-08-08 10:00:00','2026-08-03','2026-07-11');
        CREATE TABLE reputation_tiers (
            guild_id TEXT, name TEXT, symbol TEXT, min_score REAL,
            color_hex TEXT, is_default INTEGER, sort_order INTEGER
        );
        INSERT INTO reputation_tiers VALUES
        ('g1','Veteran','⚔️',500.0,'#a78bfa',0,2),
        ('g1','unranked','',0.0,'#99aab5',1,1);
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
        INSERT INTO reputation_events VALUES
        ('g1','u1',NULL,'message',1.0,NULL,'c1',NULL,'2026-08-09');
        """
    )
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_payload_endpoint_collects_from_db(client, tmp_path, monkeypatch):
    db = tmp_path / "bark.db"
    _seed_db(db)
    monkeypatch.setenv("BARK_MEDIA_DB_PATH", str(db))
    r = await client.post("/v1/payload", json={
        "kind": "profile", "guild_id": "g1", "user_id": "u1",
    }, headers=AUTH)
    assert r.status_code == 200
    data = r.json()
    assert data["reputation"]["score"] == 500.0
    assert data["reputation"]["tier"] == "Veteran"
    assert data["favorites"] == [{"channel_id": "c1", "name": None, "count": 1}]
    assert data["badges"] == []


@pytest.mark.asyncio
async def test_render_enriches_missing_blocks_from_db(client, tmp_path, monkeypatch):
    db = tmp_path / "bark.db"
    _seed_db(db)
    monkeypatch.setenv("BARK_MEDIA_DB_PATH", str(db))
    # plugin-style partial payload: live Discord facts only
    r = await client.post("/v1/render", json={
        "kind": "profile", "guild_id": "g1", "user_id": "u1",
        "payload": {"user": {"id": "u1", "display_name": "Cody", "username": "cody"}},
    }, headers=AUTH)
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    for _ in range(100):
        jr = await client.get(f"/v1/jobs/{job_id}", headers=AUTH)
        if jr.json()["status"] in ("done", "error"):
            break
        await asyncio.sleep(0.05)
    assert jr.json()["status"] == "done", jr.json()
    assert Path(jr.json()["file"]).is_file()
