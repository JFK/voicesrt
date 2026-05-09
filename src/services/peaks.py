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


async def get_or_generate_peaks(job_id: str, media_path: Path, cache_dir: Path) -> dict:
    """Return cached peaks JSON, generating it on first request."""
    cache_path = cache_dir / f"{job_id}.json"
    if cache_path.exists():
        async with aiofiles.open(cache_path, "r") as f:
            return json.loads(await f.read())

    lock = await _job_lock(job_id)
    async with lock:
        # Re-check inside the lock — another waiter may have produced it.
        if cache_path.exists():
            async with aiofiles.open(cache_path, "r") as f:
                return json.loads(await f.read())

        logger.info("Generating waveform peaks for job %s from %s", job_id, media_path.name)
        result = await generate_peaks(media_path)
        cache_dir.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(cache_path, "w") as f:
            await f.write(json.dumps(result, separators=(",", ":")))
        return result
