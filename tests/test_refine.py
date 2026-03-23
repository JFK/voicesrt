"""Tests for refine prompt selection and segment extraction."""

from src.services.refine import (
    REFINE_CAPTION_PROMPT,
    REFINE_STANDARD_PROMPT,
    REFINE_VERBATIM_PROMPT,
    _PROMPT_MAP,
    _extract_segments,
)


def test_prompt_map_has_all_modes():
    assert "verbatim" in _PROMPT_MAP
    assert "standard" in _PROMPT_MAP
    assert "caption" in _PROMPT_MAP


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


def test_standard_removes_fillers():
    """Standard prompt should instruct to remove filler words."""
    assert "remove" in REFINE_STANDARD_PROMPT.lower() or "filler" in REFINE_STANDARD_PROMPT.lower()


def test_caption_allows_splitting():
    """Caption prompt should allow segment splitting."""
    lower = REFINE_CAPTION_PROMPT.lower()
    assert "split" in lower


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
