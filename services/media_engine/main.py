"""Bark Media Engine — FastAPI service on 127.0.0.1:8094.

Renders profile cards / animated GIFs / posters for the Bark Profiles
add-on module. The only caller is the profiles plugin (localhost, Bearer
token). Async render jobs: POST /v1/render → poll GET /v1/jobs/{id} →
read the file path (same host).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from .auth import require_token
from .config import get_config
from .queue import RenderQueue
from .renderers import available_kinds
from .service import collect_payload, render_job
from .themes import list_themes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("bark.media")

app = FastAPI(title="Bark Media Engine", version=get_config().version)
queue = RenderQueue(
    max_concurrency=get_config().max_concurrency,
    timeout_s=get_config().job_timeout_s,
)


class RenderRequest(BaseModel):
    kind: str = "profile"
    guild_id: str = ""
    user_id: str = ""
    theme: Optional[str] = None
    art_mode: str = "procedural"          # procedural | auto | ai
    payload: Optional[dict] = None        # plugin-supplied data (payload-first)
    output: str = "png"                   # png | gif
    cache_ttl: int = 900


class PayloadRequest(BaseModel):
    kind: str = "profile"
    guild_id: str = ""
    user_id: str = ""


@app.get("/health")
async def health() -> dict:
    cfg = get_config()
    return {"ok": True, "version": cfg.version, "model": cfg.ai_model}


@app.get("/v1/theme")
async def theme_list(_: None = Depends(require_token)) -> dict:
    return {"themes": list_themes()}


@app.post("/v1/payload")
async def payload_collect(req: PayloadRequest, _: None = Depends(require_token)) -> dict:
    """Engine-collected data blocks for the plugin to merge with live facts."""
    return await collect_payload(req.kind, req.guild_id, req.user_id)


@app.post("/v1/render")
async def create_render_job(req: RenderRequest, _: None = Depends(require_token)) -> dict:
    if req.kind not in available_kinds():
        raise HTTPException(status_code=400, detail=f"unknown kind {req.kind!r}")
    if req.output not in ("png", "gif"):
        raise HTTPException(status_code=400, detail="output must be png or gif")

    job = queue.submit(
        req.kind,
        lambda: render_job(
            req.kind, req.guild_id, req.user_id, req.theme,
            req.art_mode, req.payload, req.output, req.cache_ttl,
        ),
    )
    return {"job_id": job.job_id, "status": job.status}


@app.get("/v1/jobs/{job_id}")
async def job_status(job_id: str, _: None = Depends(require_token)) -> dict:
    job = queue.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job")
    return {
        "job_id": job.job_id,
        "kind": job.kind,
        "status": job.status,
        "file": job.file,
        "size": job.size,
        "error": job.error,
        "cost_usd": job.cost_usd,
    }
