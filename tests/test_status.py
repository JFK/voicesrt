"""Tests for the in-memory job status pub/sub manager."""

import asyncio

import pytest

from src.services.status import JobStatusManager


@pytest.fixture
def manager():
    return JobStatusManager()


async def _consume(manager: JobStatusManager, job_id: str, sink: list):
    async for data in manager.subscribe(job_id):
        sink.append(data)
        if data and data.get("status") in ("completed", "failed"):
            break


async def _start_subscriber(manager: JobStatusManager, job_id: str) -> tuple[asyncio.Task, list]:
    """Start a subscriber and yield until it has registered with the manager.

    Polls the manager's internal subscriber map instead of sleeping for a
    fixed duration — deterministic and not flaky on slow CI runners.
    """
    sink: list = []
    expected = len(manager._subscribers.get(job_id, [])) + 1
    task = asyncio.create_task(_consume(manager, job_id, sink))
    while len(manager._subscribers.get(job_id, [])) < expected:
        await asyncio.sleep(0)
    return task, sink


@pytest.mark.asyncio
async def test_publish_subscribe(manager):
    """Subscriber receives published status events."""
    task, received = await _start_subscriber(manager, "job-1")

    await manager.publish("job-1", "extracting")
    await manager.publish("job-1", "transcribing")
    await manager.publish("job-1", "completed")

    await asyncio.wait_for(task, timeout=2.0)

    assert len(received) == 3
    assert received[0]["status"] == "extracting"
    assert received[1]["status"] == "transcribing"
    assert received[2]["status"] == "completed"


@pytest.mark.asyncio
async def test_publish_with_detail(manager):
    """Published detail field is forwarded to subscribers."""
    task, received = await _start_subscriber(manager, "job-2")

    await manager.publish("job-2", "failed", detail="Something went wrong")
    await asyncio.wait_for(task, timeout=2.0)

    assert received[0]["status"] == "failed"
    assert received[0]["detail"] == "Something went wrong"


@pytest.mark.asyncio
async def test_cleanup_on_terminal_status(manager):
    """Subscribers are cleaned up after terminal status."""
    task, _ = await _start_subscriber(manager, "job-3")
    assert "job-3" in manager._subscribers

    await manager.publish("job-3", "completed")
    await asyncio.wait_for(task, timeout=2.0)

    assert "job-3" not in manager._subscribers


@pytest.mark.asyncio
async def test_no_subscribers_publish_noop(manager):
    """Publishing to a job with no subscribers doesn't raise."""
    await manager.publish("no-one-listening", "extracting")


@pytest.mark.asyncio
async def test_multiple_subscribers(manager):
    """Multiple subscribers each receive all events."""
    t1, r1 = await _start_subscriber(manager, "job-multi")
    t2, r2 = await _start_subscriber(manager, "job-multi")

    await manager.publish("job-multi", "extracting")
    await manager.publish("job-multi", "completed")

    await asyncio.wait_for(asyncio.gather(t1, t2), timeout=2.0)

    assert len(r1) == 2
    assert len(r2) == 2


@pytest.mark.asyncio
async def test_late_subscriber_receives_terminal(manager):
    """Subscriber that arrives after a terminal publish still receives it."""
    await manager.publish("late-job", "completed")

    received = []
    async for data in manager.subscribe("late-job"):
        received.append(data)
        break

    assert len(received) == 1
    assert received[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_terminal_cache_bounded(manager):
    """The terminal-event cache evicts oldest entries past the cap."""
    from src.services.status import _TERMINAL_CACHE_SIZE

    for i in range(_TERMINAL_CACHE_SIZE + 10):
        await manager.publish(f"job-{i}", "completed")

    assert len(manager._last_terminal) == _TERMINAL_CACHE_SIZE
    # Oldest entries evicted
    assert "job-0" not in manager._last_terminal
    assert f"job-{_TERMINAL_CACHE_SIZE + 9}" in manager._last_terminal


@pytest.mark.asyncio
async def test_forget_terminal(manager):
    """forget_terminal removes a cached terminal event."""
    await manager.publish("job-x", "completed")
    assert "job-x" in manager._last_terminal
    manager.forget_terminal("job-x")
    assert "job-x" not in manager._last_terminal


@pytest.mark.asyncio
async def test_format_sse(manager):
    """SSE formatting produces correct event stream format."""
    assert manager.format_sse(None) == ": keepalive\n\n"
    result = manager.format_sse({"status": "extracting"})
    assert result.startswith("data: ")
    assert result.endswith("\n\n")
    assert '"extracting"' in result
