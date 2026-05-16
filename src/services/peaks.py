"""Server-side waveform peak extraction for the SRT editor.

Decoding multi-GB media in the browser to render a waveform freezes the tab,
so we precompute a small amplitude envelope here and ship it as JSON.
WaveSurfer takes ``peaks`` + ``duration`` and skips its own fetch/decode.
"""

import array
import asyncio
import json
import logging
from pathlib import Path

import aiofiles

from src.services.audio import get_audio_duration

logger = logging.getLogger(__name__)

# ~3000 buckets fit any reasonable screen width and yield ~10 KB JSON.
PEAKS_TARGET_BUCKETS = 3000

# Mono 4 kHz captures speech amplitude faithfully — anything higher just
# produces more bytes for ffmpeg to push through the pipe.
PEAKS_SAMPLE_RATE = 4000

_READ_CHUNK_BYTES = 64 * 1024
_BYTES_PER_SAMPLE = 2  # int16 LE


async def generate_peaks(media_path: Path, target_buckets: int = PEAKS_TARGET_BUCKETS) -> dict:
    """Stream PCM through ffmpeg and collapse into a fixed-size peak envelope.

    Memory-bounded so it works on multi-GB sources. Each emitted peak is the
    max ``|sample|`` within its bucket, normalized to ``[0, 1]``.
    """
    duration = await get_audio_duration(media_path)
    if duration <= 0:
        raise RuntimeError(f"Media has zero duration: {media_path}")

    total_samples = max(target_buckets, int(duration * PEAKS_SAMPLE_RATE))
    samples_per_bucket = max(1, total_samples // target_buckets)
    bytes_per_bucket = samples_per_bucket * _BYTES_PER_SAMPLE

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-nostdin",
        "-i",
        str(media_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(PEAKS_SAMPLE_RATE),
        "-f",
        "s16le",
        "-loglevel",
        "error",
        "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None and proc.stderr is not None

    peaks: list[float] = []
    buf = bytearray()

    try:
        while True:
            data = await proc.stdout.read(_READ_CHUNK_BYTES)
            if not data:
                break
            buf.extend(data)
            while len(buf) >= bytes_per_bucket:
                arr = array.array("h")
                arr.frombytes(bytes(buf[:bytes_per_bucket]))
                del buf[:bytes_per_bucket]
                peaks.append((max(abs(s) for s in arr) / 32768.0) if arr else 0.0)

        # Trailing partial bucket: emit only if at least half-full to avoid
        # rendering a thin sliver from a few stray samples.
        usable = (len(buf) // _BYTES_PER_SAMPLE) * _BYTES_PER_SAMPLE
        if usable >= bytes_per_bucket // 2 and usable > 0:
            arr = array.array("h")
            arr.frombytes(bytes(buf[:usable]))
            if arr:
                peaks.append(max(abs(s) for s in arr) / 32768.0)
    finally:
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()

    if proc.returncode != 0:
        stderr = (await proc.stderr.read()).decode(errors="ignore")
        raise RuntimeError(f"ffmpeg peak extraction failed: {stderr}")

    return {"peaks": peaks, "duration": duration}


# Per-job locks prevent two concurrent requests from kicking off duplicate
# ffmpeg invocations on the same source.
_locks_guard = asyncio.Lock()
_locks: dict[str, asyncio.Lock] = {}


async def _job_lock(job_id: str) -> asyncio.Lock:
    async with _locks_guard:
        lock = _locks.get(job_id)
        if lock is None:
            lock = asyncio.Lock()
            _locks[job_id] = lock
        return lock


async def _read_cached(cache_path: Path, source_key: str) -> dict | None:
    """Return cached peaks JSON only if it was generated from the same source.

    A bare ``{job_id}.json`` cache would happily serve stale peaks if the
    source path changed between requests — which is exactly what happens
    when a job's playback source moves from the original upload to the
    extracted audio. Stamping the cache with the source path and re-checking
    it on read invalidates the file without needing a separate migration.

    Treats a partial/corrupt write (concurrent writer mid-flush) as a miss
    so the caller regenerates rather than 500ing.
    """
    if not cache_path.exists():
        return None
    try:
        async with aiofiles.open(cache_path, "r") as f:
            cached = json.loads(await f.read())
    except (json.JSONDecodeError, OSError):
        return None
    if cached.get("source") != source_key:
        return None
    return cached


def _public_payload(stored: dict) -> dict:
    """Project the on-disk cache payload into the HTTP response shape.

    The ``source`` field is a cache-invalidation invariant (see
    ``_read_cached``); exposing it in the HTTP response would leak the
    server-side media path layout to the client.
    """
    return {k: v for k, v in stored.items() if k != "source"}


async def get_or_generate_peaks(job_id: str, media_path: Path, cache_dir: Path) -> dict:
    """Return cached peaks JSON, generating it on first request.

    The cache is keyed by ``job_id`` and stamped with the source media path
    so a change in the underlying file (e.g. switching from the original
    upload to the extracted audio) forces a regeneration instead of
    returning the previously cached envelope. The stamp lives only on disk
    and is stripped from the returned payload.
    """
    cache_path = cache_dir / f"{job_id}.json"
    source_key = str(media_path)

    cached = await _read_cached(cache_path, source_key)
    if cached is not None:
        return _public_payload(cached)

    lock = await _job_lock(job_id)
    async with lock:
        # Re-check inside the lock — another waiter may have produced it.
        cached = await _read_cached(cache_path, source_key)
        if cached is not None:
            return _public_payload(cached)

        logger.info("Generating waveform peaks for job %s from %s", job_id, media_path.name)
        result = await generate_peaks(media_path)
        to_store = {**result, "source": source_key}
        cache_dir.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(cache_path, "w") as f:
            await f.write(json.dumps(to_store, separators=(",", ":")))
        return result
