import asyncio
from pathlib import Path

from src.config import settings


async def extract_audio(mp4_path: Path, output_path: Path) -> float:
    """Extract audio from MP4 to WAV (16kHz mono). Returns duration in seconds."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-i", str(mp4_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        "-y",
        str(output_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed: {stderr.decode()}")

    return await get_audio_duration(output_path)


async def extract_audio_mp3(mp4_path: Path, output_path: Path) -> float:
    """Extract audio from MP4 to MP3 (for Gemini). Returns duration in seconds."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-i", str(mp4_path),
        "-vn",
        "-acodec", "libmp3lame",
        "-ar", "16000",
        "-ac", "1",
        "-q:a", "4",
        "-y",
        str(output_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg MP3 extraction failed: {stderr.decode()}")

    return await get_audio_duration(output_path)


async def get_audio_duration(path: Path) -> float:
    """Get audio file duration in seconds."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return float(stdout.decode().strip())


async def split_audio(audio_path: Path, chunk_duration_sec: int | None = None) -> list[Path]:
    """Split audio into chunks. Returns list of chunk paths."""
    if chunk_duration_sec is None:
        chunk_duration_sec = settings.whisper_chunk_duration_sec

    duration = await get_audio_duration(audio_path)
    if duration <= chunk_duration_sec:
        return [audio_path]

    chunks = []
    start = 0.0
    idx = 0
    while start < duration:
        chunk_path = audio_path.parent / f"{audio_path.stem}_chunk{idx:03d}{audio_path.suffix}"
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-i", str(audio_path),
            "-ss", str(start),
            "-t", str(chunk_duration_sec),
            "-y",
            str(chunk_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if proc.returncode == 0:
            chunks.append(chunk_path)
        start += chunk_duration_sec
        idx += 1

    return chunks
