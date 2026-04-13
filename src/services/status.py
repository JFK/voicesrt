"""In-memory job status pub/sub for SSE real-time updates."""

import asyncio
import json
import logging
from collections import OrderedDict, defaultdict

from src.constants import TERMINAL_STATUSES

logger = logging.getLogger(__name__)

# Cap on the cached terminal events. A long-running server may process tens of
# thousands of jobs over its lifetime; this is a TOCTOU safety net for
# subscribers that arrive within seconds of the publish, not a job archive.
_TERMINAL_CACHE_SIZE = 256


class JobStatusManager:
    """Manages per-job status subscriptions via asyncio.Queue."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._last_terminal: OrderedDict[str, dict] = OrderedDict()

    async def publish(self, job_id: str, status: str, detail: str | None = None, extra: dict | None = None) -> None:
        """Broadcast a status event to all subscribers of a job."""
        data: dict = {"status": status}
        if detail:
            data["detail"] = detail
        if extra:
            data.update({k: v for k, v in extra.items() if k not in {"status", "detail"}})
        for q in self._subscribers.get(job_id, []):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                logger.debug("Dropping status event for slow subscriber on job %s", job_id)
        if status in TERMINAL_STATUSES:
            self._last_terminal[job_id] = data
            self._last_terminal.move_to_end(job_id)
            while len(self._last_terminal) > _TERMINAL_CACHE_SIZE:
                self._last_terminal.popitem(last=False)
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
