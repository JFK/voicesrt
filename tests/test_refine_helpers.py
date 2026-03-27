"""Tests for refine.py helper functions (_extract_segments, _extract_corrections)."""

from src.services.refine import _extract_corrections, _extract_segments


class TestExtractSegments:
    def test_direct_array(self):
        data = [
            {"start": 0.0, "end": 1.0, "text": "hello"},
            {"start": 1.0, "end": 2.0, "text": "world"},
        ]
        result = _extract_segments(data)
        assert len(result) == 2
        assert result[0]["text"] == "hello"
        assert result[1]["start"] == 1.0

    def test_wrapped_in_segments_key(self):
        data = {
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "hello"},
            ]
        }
        result = _extract_segments(data)
        assert len(result) == 1
        assert result[0]["text"] == "hello"

    def test_wrapped_in_data_key(self):
        data = {"data": [{"start": 0.0, "end": 1.0, "text": "test"}]}
        result = _extract_segments(data)
        assert len(result) == 1

    def test_skips_invalid_segments(self):
        data = [
            {"start": 0.0, "end": 1.0, "text": "valid"},
            {"invalid": True},
            {"start": 2.0, "end": 3.0, "text": "also valid"},
        ]
        result = _extract_segments(data)
        assert len(result) == 2

    def test_converts_types(self):
        data = [{"start": "0.5", "end": "1.5", "text": "  hello  "}]
        result = _extract_segments(data)
        assert result[0]["start"] == 0.5
        assert result[0]["text"] == "hello"

    def test_empty_array(self):
        assert _extract_segments([]) == []

    def test_no_segments_key_raises(self):
        import pytest

        with pytest.raises(RuntimeError, match="Cannot find segments"):
            _extract_segments({"unknown_key": []})


class TestExtractCorrections:
    def test_dict_with_corrections(self):
        data = {
            "corrections": [
                {"index": 0, "text": "fixed", "reason": "typo"},
                {"index": 3, "text": "also fixed", "reason": "kanji"},
            ]
        }
        result = _extract_corrections(data)
        assert len(result) == 2
        assert result[0]["index"] == 0
        assert result[1]["reason"] == "kanji"

    def test_direct_array(self):
        data = [{"index": 1, "text": "corrected", "reason": "name"}]
        result = _extract_corrections(data)
        assert len(result) == 1

    def test_empty_corrections(self):
        data = {"corrections": []}
        result = _extract_corrections(data)
        assert result == []

    def test_skips_invalid(self):
        data = {
            "corrections": [
                {"index": 0, "text": "ok"},
                {"bad": True},
            ]
        }
        result = _extract_corrections(data)
        assert len(result) == 1

    def test_missing_reason_defaults_empty(self):
        data = [{"index": 0, "text": "fixed"}]
        result = _extract_corrections(data)
        assert result[0]["reason"] == ""
