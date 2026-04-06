"""In-memory job status pub/sub for SSE real-time updates."""

import asyncio
import json
import logging
from collections import defaultdict

from src.constants import TERMINAL_STATUSES

logger = logging.getLogger(__name__)


class JobStatusManager:
    """Manages per-job status subscriptions via asyncio.Queue."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        # Last terminal event per job, retained briefly so late subscribers can
        # observe completion (closes the publish-then-subscribe TOCTOU window).
        self._last_terminal: dict[str, dict] = {}

    async def publish(self, job_id: str, status: str, detail: str | None = None) -> None:
        """Broadcast a status event to all subscribers of a job."""
        data: dict = {"status": status}
        if detail:
            data["detail"] = detail
        for q in self._subscribers.get(job_id, []):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                logger.debug("Dropping status event for slow subscriber on job %s", job_id)
        if status in TERMINAL_STATUSES:
            self._last_terminal[job_id] = data
            self._subscribers.pop(job_id, None)

    async def subscribe(self, job_id: str):
        """Async generator yielding status events. Yields None as a keepalive."""
        # Closes the TOCTOU race: if the job already terminated before we
        # registered, deliver the cached event instead of hanging.
        terminal = self._last_terminal.get(job_id)
        if terminal is not None:
            yield terminal
            return

        queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._subscribers[job_id].append(queue)
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield data
                    if data.get("status") in TERMINAL_STATUSES:
                        return
                except asyncio.TimeoutError:
                    yield None
        finally:
            queues = self._subscribers.get(job_id)
            if queues is not None:
                try:
                    queues.remove(queue)
                except ValueError:
                    pass
                if not queues:
                    self._subscribers.pop(job_id, None)

    def forget_terminal(self, job_id: str) -> None:
        """Drop the cached terminal event (call when job is deleted)."""
        self._last_terminal.pop(job_id, None)

    def format_sse(self, data: dict | None) -> str:
        """Format data as an SSE message string."""
        if data is None:
            return ": keepalive\n\n"
        return f"data: {json.dumps(data)}\n\n"


status_manager = JobStatusManager()
