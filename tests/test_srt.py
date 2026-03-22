from src.services.srt import generate_srt, seconds_to_srt_time


def test_seconds_to_srt_time_zero():
    assert seconds_to_srt_time(0.0) == "00:00:00,000"


def test_seconds_to_srt_time_simple():
    assert seconds_to_srt_time(1.5) == "00:00:01,500"


def test_seconds_to_srt_time_minutes():
    assert seconds_to_srt_time(65.123) == "00:01:05,123"


def test_seconds_to_srt_time_hours():
    assert seconds_to_srt_time(3661.999) == "01:01:01,999"


def test_generate_srt(sample_segments):
    result = generate_srt(sample_segments)
    assert "00:00:00,000 --> 00:00:02,500" in result
    assert "00:00:03,000 --> 00:00:05,800" in result
    assert "Hello, welcome to the video." in result
    assert "Today we will discuss Python." in result


def test_generate_srt_skips_empty():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "Hello"},
        {"start": 1.0, "end": 2.0, "text": "  "},
        {"start": 2.0, "end": 3.0, "text": "World"},
    ]
    result = generate_srt(segments)
    assert "1\n" in result
    assert "2\n" in result
    assert "3\n" not in result


def test_generate_srt_no_newlines_in_text():
    """SRT text should be clean single-line for editing software compatibility."""
    segments = [
        {"start": 0.0, "end": 5.0, "text": "This is a long sentence that should remain on one line without wrapping"},
    ]
    result = generate_srt(segments)
    text_line = result.strip().split("\n")[2]
    assert "\n" not in text_line
    assert text_line == "This is a long sentence that should remain on one line without wrapping"
