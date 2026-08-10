from fastapi.testclient import TestClient

from services.media_engine.main import app

client = TestClient(app)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["version"]
    assert body["model"] == "gpt-5.6-sol"


def test_render_requires_token(monkeypatch):
    monkeypatch.setenv("BARK_MEDIA_ENGINE_TOKEN", "test-token")
    # no credentials -> 401
    assert client.post("/v1/render", json={}).status_code == 401
    # wrong credentials -> 401
    r = client.post(
        "/v1/render", json={}, headers={"Authorization": "Bearer wrong"}
    )
    assert r.status_code == 401
    # correct credentials -> 200 (job accepted)
    r = client.post(
        "/v1/render", json={}, headers={"Authorization": "Bearer test-token"}
    )
    assert r.status_code == 200
    assert r.json()["job_id"]


def test_render_503_when_token_unconfigured():
    # no BARK_MEDIA_ENGINE_TOKEN in env -> engine refuses to serve
    assert client.post("/v1/render", json={}).status_code == 503


def test_theme_requires_token(monkeypatch):
    monkeypatch.setenv("BARK_MEDIA_ENGINE_TOKEN", "test-token")
    r = client.get("/v1/theme", headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 200
    names = [t["name"] for t in r.json()["themes"]]
    assert names == ["bark"]


def test_unknown_job_404(monkeypatch):
    monkeypatch.setenv("BARK_MEDIA_ENGINE_TOKEN", "test-token")
    r = client.get(
        "/v1/jobs/nope", headers={"Authorization": "Bearer test-token"}
    )
    assert r.status_code == 404
