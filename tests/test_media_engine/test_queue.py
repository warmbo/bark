"""Async render queue: lifecycle, errors, concurrency cap."""

import asyncio

import pytest

from services.media_engine.queue import RenderQueue


async def _wait(jobs, timeout=5.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while any(j.status in ("queued", "rendering") for j in jobs):
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError("jobs did not finish")
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_job_completes():
    q = RenderQueue(max_concurrency=2, timeout_s=5)

    async def factory():
        await asyncio.sleep(0.01)
        return "/tmp/out.png", 42

    job = q.submit("profile", factory)
    await _wait([job])
    assert job.status == "done"
    assert job.file == "/tmp/out.png"
    assert job.size == 42


@pytest.mark.asyncio
async def test_job_error():
    q = RenderQueue(max_concurrency=2, timeout_s=5)

    async def factory():
        raise RuntimeError("kaboom")

    job = q.submit("profile", factory)
    await _wait([job])
    assert job.status == "error"
    assert "kaboom" in job.error


@pytest.mark.asyncio
async def test_job_timeout():
    q = RenderQueue(max_concurrency=2, timeout_s=1)

    async def factory():
        await asyncio.sleep(10)
        return "/tmp/x.png", 1

    job = q.submit("profile", factory)
    await _wait([job])
    assert job.status == "error"
    assert "timed out" in job.error


@pytest.mark.asyncio
async def test_concurrency_capped():
    q = RenderQueue(max_concurrency=2, timeout_s=5)
    active = 0
    peak = 0

    async def slow():
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.08)
        active -= 1
        return "/tmp/x.png", 1

    jobs = [q.submit("profile", slow) for _ in range(4)]
    await _wait(jobs)
    assert peak == 2
    assert all(j.status == "done" for j in jobs)


@pytest.mark.asyncio
async def test_unknown_job_is_none():
    q = RenderQueue()
    assert q.get("nope") is None
