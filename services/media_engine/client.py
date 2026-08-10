"""Shared media-engine client — any bark module or plugin can drive renders.

The engine runs as a local service (``bark-media-engine.service`` per
instance) on the same host; the returned file paths are read directly.
Config via env: ``BARK_MEDIA_ENGINE_URL`` (default http://127.0.0.1:8094)
and ``BARK_MEDIA_ENGINE_TOKEN``.

Example (a module wanting a rendered card):
    client = MediaEngineClient()
    data = await client.collect_payload("profile", guild_id, user_id)
    path = await client.render("profile", guild_id, user_id, payload=data)
    # path is a local PNG — attach it, post it, whatever
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx

logger = logging.getLogger("bark.media_engine.client")

DEFAULT_URL = "http://127.0.0.1:8094"


class MediaEngineError(RuntimeError):
    """The engine rejected or failed the job."""


class MediaEngineUnavailableError(MediaEngineError):
    """The engine could not be reached at all."""


class MediaEngineClient:
    def __init__(self, base_url: str | None = None, token: str | None = None,
                 timeout: float = 15.0, poll_interval: float = 0.3,
                 poll_max: int = 60,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = (base_url or os.environ.get("BARK_MEDIA_ENGINE_URL", DEFAULT_URL)).rstrip("/")
        self.token = token or os.environ.get("BARK_MEDIA_ENGINE_TOKEN", "")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.poll_max = poll_max
        self._transport = transport  # test seam (httpx.MockTransport)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    async def health(self) -> bool:
        """True when the engine is up (health is open, no token needed)."""
        try:
            async with self._client(5) as client:
                resp = await client.get(f"{self.base_url}/health")
            return resp.status_code == 200 and bool(resp.json().get("ok"))
        except Exception:
            return False

    async def collect_payload(self, kind: str, guild_id, user_id) -> dict:
        """Engine-side data blocks (reputation/activity/badges/favorites)."""
        try:
            async with self._client(self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/payload",
                    json={"kind": kind, "guild_id": str(guild_id), "user_id": str(user_id)},
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:
            raise MediaEngineUnavailableError(f"media engine unreachable: {exc}") from exc

    async def render(self, kind: str, guild_id, user_id, payload: dict | None = None, *,
                     theme: str = "bark", art_mode: str = "procedural",
                     output: str = "png", cache_ttl: int = 900) -> str:
        """Submit a render job, poll to completion, return the local file path."""
        body = {
            "kind": kind,
            "guild_id": str(guild_id),
            "user_id": str(user_id),
            "theme": theme,
            "art_mode": art_mode,
            "payload": payload or {},
            "output": output,
            "cache_ttl": cache_ttl,
        }
        try:
            async with self._client(self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/render", json=body, headers=self._headers()
                )
                resp.raise_for_status()
                job_id = resp.json()["job_id"]

                for _ in range(self.poll_max):
                    await asyncio.sleep(self.poll_interval)
                    job = (await client.get(
                        f"{self.base_url}/v1/jobs/{job_id}", headers=self._headers()
                    )).json()
                    if job["status"] == "done":
                        return job["file"]
                    if job["status"] == "error":
                        raise MediaEngineError(job.get("error") or "render failed")
                raise MediaEngineError("render job did not finish in time")
        except httpx.HTTPError as exc:
            raise MediaEngineUnavailableError(f"media engine unreachable: {exc}") from exc
