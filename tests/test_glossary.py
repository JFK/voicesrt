"""Tests for glossary processing logic."""

from src.services.transcribe import _build_whisper_prompt


def test_build_whisper_prompt_basic():
    glossary = "漢字:かんじ\nOpenAI:オープンエーアイ"
    result = _build_whisper_prompt(glossary)
    assert "漢字" in result
    assert "かんじ" in result
    assert "OpenAI" in result
    assert "オープンエーアイ" in result


def test_build_whisper_prompt_empty():
    assert _build_whisper_prompt("") == ""
    assert _build_whisper_prompt("   ") == ""


def test_build_whisper_prompt_no_reading():
    """Lines without colon should be included as-is."""
    glossary = "Kubernetes\nDocker"
    result = _build_whisper_prompt(glossary)
    assert "Kubernetes" in result
    assert "Docker" in result


def test_build_whisper_prompt_fullwidth_colon():
    """Full-width colon (：) should also work."""
    glossary = "漢字：かんじ"
    result = _build_whisper_prompt(glossary)
    assert "漢字" in result
    assert "かんじ" in result


def test_build_whisper_prompt_skips_empty_lines():
    glossary = "term1:reading1\n\n\nterm2:reading2"
    result = _build_whisper_prompt(glossary)
    parts = result.split("、")
    # Should have 4 parts (2 terms + 2 readings), no empty entries
    assert "" not in parts
    assert len(parts) == 4


def test_build_whisper_prompt_separator():
    """Terms should be joined with Japanese comma."""
    glossary = "A:a\nB:b"
    result = _build_whisper_prompt(glossary)
    assert "、" in result


def test_glossary_merge_logic():
    """Test that global and job glossaries merge correctly."""
    global_glossary = "global_term:reading1"
    job_glossary = "job_term:reading2"

    combined = "\n".join(filter(None, [global_glossary.strip(), job_glossary.strip()]))
    assert "global_term" in combined
    assert "job_term" in combined


def test_glossary_merge_empty_global():
    global_glossary = ""
    job_glossary = "job_term:reading"

    combined = "\n".join(filter(None, [global_glossary.strip(), job_glossary.strip()]))
    assert combined == "job_term:reading"


def test_glossary_merge_empty_job():
    global_glossary = "global_term:reading"
    job_glossary = ""

    combined = "\n".join(filter(None, [global_glossary.strip(), job_glossary.strip()]))
    assert combined == "global_term:reading"


def test_glossary_merge_both_empty():
    combined = "\n".join(filter(None, ["", ""]))
    assert combined == ""
