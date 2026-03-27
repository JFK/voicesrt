"""Tests for src/services/utils.py - JSON repair, markdown stripping, token extraction."""

import pytest

from src.services.utils import _repair_truncated_json, parse_json_response, strip_markdown_fence


class TestStripMarkdownFence:
    def test_no_fence(self):
        assert strip_markdown_fence('{"key": "value"}') == '{"key": "value"}'

    def test_json_fence(self):
        text = '```json\n{"key": "value"}\n```'
        assert strip_markdown_fence(text) == '{"key": "value"}'

    def test_plain_fence(self):
        text = "```\n[1, 2, 3]\n```"
        assert strip_markdown_fence(text) == "[1, 2, 3]"

    def test_no_closing_fence(self):
        text = '```json\n{"key": "value"}'
        assert strip_markdown_fence(text) == '{"key": "value"}'

    def test_whitespace(self):
        text = '  ```json\n{"a": 1}\n```  '
        assert strip_markdown_fence(text) == '{"a": 1}'


class TestRepairTruncatedJson:
    def test_truncated_array(self):
        text = '[{"start": 0.0, "end": 1.0, "text": "hello"}, {"start": 1.0, "end": 2.0, "text": "wor'
        result = _repair_truncated_json(text)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["text"] == "hello"

    def test_truncated_wrapped_object(self):
        text = '{"segments": [{"start": 0.0, "end": 1.0, "text": "hello"}, {"start": 1.0, "end": 2.0, "text": "trun'
        result = _repair_truncated_json(text)
        assert isinstance(result, dict)
        assert "segments" in result
        assert len(result["segments"]) == 1

    def test_complete_json_not_repaired(self):
        text = '[{"start": 0.0, "end": 1.0, "text": "hello"}]'
        # Complete JSON should just parse normally via parse_json_response
        result = _repair_truncated_json(text)
        assert isinstance(result, list)

    def test_deeply_nested_truncation(self):
        text = '{"data": {"segments": [{"start": 0.0, "end": 1.0, "text": "ok"}, {"start": 1.0'
        result = _repair_truncated_json(text)
        assert isinstance(result, dict)

    def test_unrepairable(self):
        with pytest.raises(Exception):
            _repair_truncated_json("not json at all")

    def test_trailing_comma(self):
        text = '[{"a": 1}, {"b": 2},'
        result = _repair_truncated_json(text)
        assert isinstance(result, list)
        assert len(result) == 2


class TestParseJsonResponse:
    def test_valid_json(self):
        result = parse_json_response('[{"start": 0, "end": 1, "text": "hi"}]')
        assert isinstance(result, list)
        assert result[0]["text"] == "hi"

    def test_valid_dict(self):
        result = parse_json_response('{"title": "test", "tags": ["a"]}')
        assert result["title"] == "test"

    def test_markdown_wrapped(self):
        result = parse_json_response('```json\n{"key": "val"}\n```')
        assert result["key"] == "val"

    def test_truncated_with_repair(self):
        text = '[{"start": 0.0, "end": 1.0, "text": "hello"}, {"start": 1.0, "end": 2.0, "text": "wor'
        result = parse_json_response(text, context="test")
        assert isinstance(result, list)
        assert len(result) == 1

    def test_invalid_json_raises(self):
        with pytest.raises(RuntimeError, match="Invalid JSON"):
            parse_json_response("not json", context="test")

    def test_empty_object(self):
        result = parse_json_response("{}")
        assert result == {}

    def test_empty_array(self):
        result = parse_json_response("[]")
        assert result == []
