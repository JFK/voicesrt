"""In-memory job status pub/sub for SSE real-time updates."""

import asyncio
import json
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class JobStatusManager:
    """Manages per-job status subscriptions via asyncio.Queue."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)

    async def publish(self, job_id: str, status: str, detail: str | None = None) -> None:
        """Broadcast a status event to all subscribers of a job."""
        data = {"status": status}
        if detail:
            data["detail"] = detail
        queues = self._subscribers.get(job_id, [])
        for q in queues:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                logger.debug("Dropping status event for slow subscriber on job %s", job_id)
        # Clean up subscribers on terminal status
        if status in ("completed", "failed"):
            self._subscribers.pop(job_id, None)

    async def subscribe(self, job_id: str):
        """Async generator yielding status events. Yields None as keepalive."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._subscribers[job_id].append(queue)
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield data
                    if data.get("status") in ("completed", "failed"):
                        return
                except asyncio.TimeoutError:
                    yield None  # keepalive
        finally:
            try:
                self._subscribers[job_id].remove(queue)
            except (ValueError, KeyError):
                pass
            # Clean up empty subscriber lists
            if job_id in self._subscribers and not self._subscribers[job_id]:
                del self._subscribers[job_id]

    def format_sse(self, data: dict | None) -> str:
        """Format data as an SSE message string."""
        if data is None:
            return ": keepalive\n\n"
        return f"data: {json.dumps(data)}\n\n"


# Module-level singleton
status_manager = JobStatusManager()
