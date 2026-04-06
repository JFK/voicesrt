"""Tests for the in-memory job status pub/sub manager."""

import asyncio

import pytest

from src.services.status import JobStatusManager


@pytest.fixture
def manager():
    return JobStatusManager()


@pytest.mark.asyncio
async def test_publish_subscribe(manager):
    """Subscriber receives published status events."""
    received = []

    async def consume():
        async for data in manager.subscribe("job-1"):
            received.append(data)
            if data and data.get("status") == "completed":
                break

    task = asyncio.create_task(consume())

    await asyncio.sleep(0.01)
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
    received = []

    async def consume():
        async for data in manager.subscribe("job-2"):
            received.append(data)
            if data and data.get("status") == "failed":
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)

    await manager.publish("job-2", "failed", detail="Something went wrong")
    await asyncio.wait_for(task, timeout=2.0)

    assert received[0]["status"] == "failed"
    assert received[0]["detail"] == "Something went wrong"


@pytest.mark.asyncio
async def test_cleanup_on_terminal_status(manager):
    """Subscribers are cleaned up after terminal status."""

    async def consume():
        async for data in manager.subscribe("job-3"):
            if data and data.get("status") == "completed":
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)

    assert "job-3" in manager._subscribers
    await manager.publish("job-3", "completed")
    await asyncio.wait_for(task, timeout=2.0)
    await asyncio.sleep(0.01)  # allow finally block to run

    # Subscribers cleaned up
    assert "job-3" not in manager._subscribers


@pytest.mark.asyncio
async def test_no_subscribers_publish_noop(manager):
    """Publishing to a job with no subscribers doesn't raise."""
    await manager.publish("no-one-listening", "extracting")


@pytest.mark.asyncio
async def test_multiple_subscribers(manager):
    """Multiple subscribers each receive all events."""
    results = [[], []]

    async def consume(idx):
        async for data in manager.subscribe("job-multi"):
            results[idx].append(data)
            if data and data.get("status") == "completed":
                break

    t1 = asyncio.create_task(consume(0))
    t2 = asyncio.create_task(consume(1))
    await asyncio.sleep(0.01)

    await manager.publish("job-multi", "extracting")
    await manager.publish("job-multi", "completed")

    await asyncio.wait_for(asyncio.gather(t1, t2), timeout=2.0)

    assert len(results[0]) == 2
    assert len(results[1]) == 2


@pytest.mark.asyncio
async def test_format_sse(manager):
    """SSE formatting produces correct event stream format."""
    assert manager.format_sse(None) == ": keepalive\n\n"
    result = manager.format_sse({"status": "extracting"})
    assert result.startswith("data: ")
    assert result.endswith("\n\n")
    assert '"extracting"' in result
