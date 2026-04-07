import asyncio
import logging
import re
from pathlib import Path

from src.config import settings

logger = logging.getLogger(__name__)

# Silence detection defaults — tuned for spoken-content audio (lectures,
# meetings, narration). Used to anchor chunk boundaries on natural pauses
# instead of cutting in the middle of a word.
_SILENCE_NOISE_DB = -30.0
_SILENCE_MIN_DUR = 0.3
_SILENCE_SEARCH_WINDOW_SEC = 15.0
# Reject anchors that would create chunks shorter than this many seconds.
_MIN_CHUNK_SEC = 1.0

_SILENCE_RE = re.compile(r"silence_(start|end):\s*(-?\d+\.?\d*)")


async def _run_ffmpeg(*args: str) -> bytes:
    """Run ffmpeg/ffprobe command and return stderr. Raises on failure."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg command failed: {stderr.decode()}")
    return stdout


async def extract_audio(mp4_path: Path, output_path: Path) -> float:
    """Extract audio from MP4 to WAV (16kHz mono). Returns duration in seconds."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    await _run_ffmpeg(
        "ffmpeg",
        "-i",
        str(mp4_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-y",
        str(output_path),
    )
    return await get_audio_duration(output_path)


async def extract_audio_mp3(mp4_path: Path, output_path: Path) -> float:
    """Extract audio from MP4 to MP3 (for Gemini). Returns duration in seconds."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    await _run_ffmpeg(
        "ffmpeg",
        "-i",
        str(mp4_path),
        "-vn",
        "-acodec",
        "libmp3lame",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-q:a",
        "4",
        "-y",
        str(output_path),
    )
    return await get_audio_duration(output_path)


async def get_audio_duration(path: Path) -> float:
    """Get audio file duration in seconds."""
    stdout = await _run_ffmpeg(
        "ffprobe",
        "-v",
        "quiet",
        "-show_entries",
        "format=duration",
        "-of",
        "csv=p=0",
        str(path),
    )
    try:
        return float(stdout.decode().strip())
    except ValueError as e:
        raise RuntimeError(f"Could not parse audio duration from ffprobe output: {e}")


def _parse_silence_ranges(stderr_text: str) -> list[tuple[float, float]]:
    """Parse ffmpeg silencedetect stderr into a list of (start, end) times.

    Unmatched start lines (no following end) are dropped.
    """
    ranges: list[tuple[float, float]] = []
    current_start: float | None = None
    for line in stderr_text.splitlines():
        m = _SILENCE_RE.search(line)
        if not m:
            continue
        kind, value = m.group(1), float(m.group(2))
        if kind == "start":
            current_start = value
        elif kind == "end" and current_start is not None:
            ranges.append((current_start, value))
            current_start = None
    return ranges


async def find_all_silences(audio_path: Path) -> list[tuple[float, float]]:
    """Run ffmpeg silencedetect once over the entire file.

    Returns list of (start, end) silence ranges, or empty list if detection
    fails — callers fall back to fixed-length cuts.
    """
    # -nostats / -hide_banner suppress per-frame progress output so stderr
    # only contains silencedetect lines (plus a small banner). Without these,
    # `communicate()` would buffer megabytes of progress text for long files.
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-nostats",
        "-hide_banner",
        "-i",
        str(audio_path),
        "-af",
        f"silencedetect=noise={_SILENCE_NOISE_DB}dB:d={_SILENCE_MIN_DUR}",
        "-f",
        "null",
        "-",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.debug("silencedetect failed (returncode=%d) — falling back", proc.returncode)
        return []
    return _parse_silence_ranges(stderr.decode(errors="replace"))


def _nearest_silence_midpoint(
    silences: list[tuple[float, float]],
    target: float,
    window: float,
) -> float | None:
    """Return midpoint of the silence closest to `target`, or None if none within ±window."""
    candidates = [(s + e) / 2 for s, e in silences if abs((s + e) / 2 - target) <= window]
    if not candidates:
        return None
    return min(candidates, key=lambda m: abs(m - target))


def _compute_chunk_boundaries(
    total_duration: float,
    chunk_duration_sec: float,
    silences: list[tuple[float, float]],
) -> list[float]:
    """Compute chunk boundary timestamps using silence anchoring.

    Each target boundary at N * chunk_duration_sec is snapped to the nearest
    silence midpoint within ±_SILENCE_SEARCH_WINDOW_SEC, falling back to the
    fixed-length boundary when no silence is in range. Anchors that would
    produce a chunk shorter than _MIN_CHUNK_SEC on either side are rejected.
    """
    boundaries: list[float] = [0.0]
    target = chunk_duration_sec
    while target < total_duration:
        anchor = _nearest_silence_midpoint(silences, target, _SILENCE_SEARCH_WINDOW_SEC)
        if anchor is None or anchor <= boundaries[-1] + _MIN_CHUNK_SEC:
            anchor = target
        if anchor >= total_duration - _MIN_CHUNK_SEC:
            break
        boundaries.append(anchor)
        target = anchor + chunk_duration_sec
    boundaries.append(total_duration)
    return boundaries


async def split_audio(audio_path: Path, chunk_duration_sec: int | None = None) -> list[Path]:
    """Split audio into chunks anchored on silences. Returns list of chunk paths."""
    if chunk_duration_sec is None:
        chunk_duration_sec = settings.whisper_chunk_duration_sec

    duration = await get_audio_duration(audio_path)
    if duration <= chunk_duration_sec:
        return [audio_path]

    silences = await find_all_silences(audio_path)
    boundaries = _compute_chunk_boundaries(duration, float(chunk_duration_sec), silences)

    # If boundary computation rejected every internal split point (e.g. the
    # only target was within _MIN_CHUNK_SEC of the end), boundaries collapses
    # to [0.0, total_duration]. Return the original path so the caller's
    # `len(chunks) == 1` short-circuit avoids a redundant ffmpeg invocation
    # and a leftover _chunk000 file.
    if len(boundaries) == 2:
        return [audio_path]

    chunks = []
    for idx in range(len(boundaries) - 1):
        chunk_start = boundaries[idx]
        chunk_len = boundaries[idx + 1] - chunk_start
        chunk_path = audio_path.parent / f"{audio_path.stem}_chunk{idx:03d}{audio_path.suffix}"
        try:
            # -ss before -i enables fast seek; -c copy avoids re-encoding
            # since chunks are extracted from already-decoded WAV/MP3 output.
            await _run_ffmpeg(
                "ffmpeg",
                "-ss",
                str(chunk_start),
                "-i",
                str(audio_path),
                "-t",
                str(chunk_len),
                "-c",
                "copy",
                "-y",
                str(chunk_path),
            )
            chunks.append(chunk_path)
        except RuntimeError:
            logger.warning("Failed to create chunk %d, skipping", idx)

    return chunks
