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


def _parse_silence_ranges(stderr_text: str, offset_sec: float) -> list[tuple[float, float]]:
    """Parse ffmpeg silencedetect stderr into a list of (start, end) absolute times.

    `offset_sec` is added to convert seek-relative timestamps back to absolute.
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
            ranges.append((current_start + offset_sec, value + offset_sec))
            current_start = None
    return ranges


async def find_silence_near(
    audio_path: Path,
    target_sec: float,
    window_sec: float = _SILENCE_SEARCH_WINDOW_SEC,
    noise_db: float = _SILENCE_NOISE_DB,
    min_silence_dur: float = _SILENCE_MIN_DUR,
) -> float | None:
    """Find a silence near `target_sec` and return its midpoint (absolute time).

    Searches the [target - window, target + window] interval using ffmpeg
    `silencedetect`. Returns the midpoint of the silence whose midpoint is
    closest to `target_sec`, or `None` if no silence is detected (caller
    should fall back to a fixed-length cut).
    """
    seek_start = max(0.0, target_sec - window_sec)
    duration = window_sec * 2

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-ss",
        str(seek_start),
        "-i",
        str(audio_path),
        "-t",
        str(duration),
        "-af",
        f"silencedetect=noise={noise_db}dB:d={min_silence_dur}",
        "-f",
        "null",
        "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.debug("silencedetect failed (returncode=%d) — falling back", proc.returncode)
        return None

    ranges = _parse_silence_ranges(stderr.decode(errors="replace"), seek_start)
    if not ranges:
        return None

    best = min(ranges, key=lambda r: abs((r[0] + r[1]) / 2 - target_sec))
    return (best[0] + best[1]) / 2


async def _compute_chunk_boundaries(
    audio_path: Path,
    total_duration: float,
    chunk_duration_sec: float,
) -> list[float]:
    """Compute chunk boundary timestamps using silence anchoring.

    Each target boundary at N * chunk_duration_sec is snapped to the nearest
    silence midpoint, falling back to the fixed-length boundary when no
    suitable silence is found. Anchors that would produce a chunk shorter
    than `_MIN_CHUNK_SEC` are rejected.
    """
    boundaries: list[float] = [0.0]
    target = chunk_duration_sec
    while target < total_duration:
        anchor = await find_silence_near(audio_path, target)
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

    boundaries = await _compute_chunk_boundaries(audio_path, duration, float(chunk_duration_sec))

    chunks = []
    for idx in range(len(boundaries) - 1):
        chunk_start = boundaries[idx]
        chunk_len = boundaries[idx + 1] - chunk_start
        chunk_path = audio_path.parent / f"{audio_path.stem}_chunk{idx:03d}{audio_path.suffix}"
        try:
            await _run_ffmpeg(
                "ffmpeg",
                "-i",
                str(audio_path),
                "-ss",
                str(chunk_start),
                "-t",
                str(chunk_len),
                "-y",
                str(chunk_path),
            )
            chunks.append(chunk_path)
        except RuntimeError:
            logger.warning("Failed to create chunk %d, skipping", idx)

    return chunks
