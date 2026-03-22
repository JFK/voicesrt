from pathlib import Path


def seconds_to_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp format: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = round((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(segments: list[dict]) -> str:
    """Generate SRT content from segments.

    Each segment: {"start": float, "end": float, "text": str}
    """
    lines = []
    idx = 1
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        start = seconds_to_srt_time(seg["start"])
        end = seconds_to_srt_time(seg["end"])
        lines.append(str(idx))
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
        idx += 1

    return "\n".join(lines)


def save_srt(content: str, output_path: Path) -> None:
    """Save SRT content to file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
