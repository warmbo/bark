"""Async render queue with an in-process job registry.

Jobs run on the running event loop with a concurrency semaphore; the plugin
polls ``GET /v1/jobs/{id}`` until the job lands in done/error. Done/error
jobs are pruned after a few minutes.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

JOB_MAX_AGE_S = 600


@dataclass
class Job:
    job_id: str
    kind: str
    status: str = "queued"        # queued | rendering | done | error
    file: str | None = None
    size: int = 0
    error: str | None = None
    cost_usd: float = 0.0
    created_at: float = field(default_factory=time.time)


class RenderQueue:
    def __init__(self, max_concurrency: int = 2, timeout_s: int = 60):
        self._sem = asyncio.Semaphore(max_concurrency)
        self._timeout_s = timeout_s
        self._jobs: dict[str, Job] = {}

    def submit(self, kind: str, factory: Callable[[], Awaitable[tuple[str, int]]]) -> Job:
        """Schedule ``factory`` (returns (file_path, size)); returns the Job."""
        self.prune()
        job = Job(job_id=uuid.uuid4().hex[:12], kind=kind)
        self._jobs[job.job_id] = job
        asyncio.get_running_loop().create_task(self._run(job, factory))
        return job

    async def _run(self, job: Job, factory: Callable[[], Awaitable[tuple[str, int]]]) -> None:
        async with self._sem:
            job.status = "rendering"
            try:
                file_path, size = await asyncio.wait_for(factory(), timeout=self._timeout_s)
                job.file, job.size, job.status = file_path, int(size), "done"
            except asyncio.TimeoutError:
                job.status, job.error = "error", "render timed out"
            except Exception as exc:  # noqa: BLE001 — job failure is a result, not a crash
                job.status, job.error = "error", str(exc)

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def prune(self, max_age_s: int = JOB_MAX_AGE_S) -> None:
        cutoff = time.time() - max_age_s
        stale = [
            jid for jid, job in self._jobs.items()
            if job.status in ("done", "error") and job.created_at < cutoff
        ]
        for jid in stale:
            self._jobs.pop(jid, None)
