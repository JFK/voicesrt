"""Tests for refine prompt selection, segment extraction, and verification."""

from src.services.refine import (
    _PROMPT_MAP,
    REFINE_VERBATIM_PROMPT,
    VALID_REFINE_MODES,
    VERIFY_PROMPT,
    _build_full_text,
    _extract_corrections,
    _extract_segments,
)


def test_prompt_map_only_verbatim():
    """verbatim is the only supported mode; standard/caption were removed (#86)."""
    assert set(_PROMPT_MAP) == {"verbatim"}
    assert VALID_REFINE_MODES == frozenset({"verbatim"})


def test_prompt_map_values_are_strings():
    for mode, prompt in _PROMPT_MAP.items():
        assert isinstance(prompt, str), f"{mode} prompt is not a string"
        assert len(prompt) > 100, f"{mode} prompt is too short"


def test_prompts_have_required_placeholders():
    """All prompts must contain {segments_json} and {glossary_section}."""
    for mode, prompt in _PROMPT_MAP.items():
        assert "{segments_json}" in prompt, f"{mode} missing {{segments_json}}"
        assert "{glossary_section}" in prompt, f"{mode} missing {{glossary_section}}"


def test_verbatim_keeps_fillers():
    """Verbatim prompt should instruct to keep filler words."""
    assert "keep" in REFINE_VERBATIM_PROMPT.lower() or "残す" in REFINE_VERBATIM_PROMPT
    assert "filler" in REFINE_VERBATIM_PROMPT.lower()


def test_verbatim_preserves_timestamps():
    """Verbatim prompt must instruct to keep timestamps unchanged."""
    assert "timestamp" in REFINE_VERBATIM_PROMPT.lower()


def test_extract_segments_from_dict():
    data = {"segments": [{"start": 0.0, "end": 1.0, "text": "hello"}]}
    result = _extract_segments(data)
    assert len(result) == 1
    assert result[0]["text"] == "hello"
    assert result[0]["start"] == 0.0
    assert result[0]["end"] == 1.0


def test_extract_segments_from_list():
    data = [{"start": 0.0, "end": 1.0, "text": "hello"}]
    result = _extract_segments(data)
    assert len(result) == 1


def test_extract_segments_skips_invalid():
    data = [
        {"start": 0.0, "end": 1.0, "text": "valid"},
        {"start": 1.0},  # missing end and text
        {"start": 2.0, "end": 3.0, "text": "also valid"},
    ]
    result = _extract_segments(data)
    assert len(result) == 2


def test_extract_segments_strips_text():
    data = [{"start": 0.0, "end": 1.0, "text": "  hello  "}]
    result = _extract_segments(data)
    assert result[0]["text"] == "hello"


def test_extract_segments_converts_types():
    """start/end should be float, text should be str."""
    data = [{"start": "1", "end": "2", "text": 123}]
    result = _extract_segments(data)
    assert result[0]["start"] == 1.0
    assert result[0]["end"] == 2.0
    assert result[0]["text"] == "123"


def test_extract_segments_alternative_keys():
    """Should find segments under common wrapper keys."""
    for key in ("segments", "data", "results", "subtitles"):
        data = {key: [{"start": 0.0, "end": 1.0, "text": "hello"}]}
        result = _extract_segments(data)
        assert len(result) == 1, f"Failed for key: {key}"


def test_extract_segments_unknown_dict_raises():
    import pytest

    with pytest.raises(RuntimeError, match="Cannot find segments"):
        _extract_segments({"unknown_key": []})


def test_extract_segments_unexpected_type_raises():
    import pytest

    with pytest.raises(RuntimeError, match="Unexpected response type"):
        _extract_segments("not a dict or list")


# --- Verify tests ---


def test_verify_prompt_has_placeholders():
    assert "{full_text}" in VERIFY_PROMPT
    assert "{glossary_section}" in VERIFY_PROMPT


def test_build_full_text():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "Hello"},
        {"start": 1.0, "end": 2.0, "text": "World"},
    ]
    result = _build_full_text(segments)
    assert "[0] Hello" in result
    assert "[1] World" in result


def test_extract_corrections_from_dict():
    data = {
        "corrections": [
            {"index": 0, "text": "fixed", "reason": "typo"},
            {"index": 2, "text": "also fixed"},
        ]
    }
    result = _extract_corrections(data)
    assert len(result) == 2
    assert result[0]["index"] == 0
    assert result[0]["text"] == "fixed"
    assert result[0]["reason"] == "typo"
    assert result[1]["reason"] == ""


def test_extract_corrections_empty():
    data = {"corrections": []}
    result = _extract_corrections(data)
    assert result == []


def test_extract_corrections_from_list():
    data = [{"index": 0, "text": "fixed", "reason": "err"}]
    result = _extract_corrections(data)
    assert len(result) == 1


def test_extract_corrections_skips_invalid():
    data = {
        "corrections": [
            {"index": 0, "text": "valid"},
            {"index": 1},  # missing text
            "not a dict",
        ]
    }
    result = _extract_corrections(data)
    assert len(result) == 1


def test_extract_corrections_unexpected_type():
    import pytest

    with pytest.raises(RuntimeError, match="Unexpected verify response type"):
        _extract_corrections("not valid")
