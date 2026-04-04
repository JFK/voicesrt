"""Tests for i18n translation system."""

from src.templating import _get_nested, _translations, get_translator


def test_translations_loaded():
    """Both en and ja translation files should be loaded."""
    assert "en" in _translations
    assert "ja" in _translations


def test_translations_have_same_keys():
    """en.json and ja.json should have identical key structures."""

    def get_keys(d, prefix=""):
        keys = set()
        for k, v in d.items():
            full = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                keys |= get_keys(v, full)
            else:
                keys.add(full)
        return keys

    en_keys = get_keys(_translations["en"])
    ja_keys = get_keys(_translations["ja"])
    assert en_keys == ja_keys, f"Missing in ja: {en_keys - ja_keys}, Missing in en: {ja_keys - en_keys}"


def test_get_nested_simple():
    d = {"a": {"b": "hello"}}
    assert _get_nested(d, "a.b") == "hello"


def test_get_nested_missing_returns_default():
    d = {"a": {"b": "hello"}}
    assert _get_nested(d, "a.c") == ""
    assert _get_nested(d, "x.y", "fallback") == "fallback"


def test_get_nested_non_string_returns_default():
    d = {"a": {"b": {"c": "nested"}}}
    assert _get_nested(d, "a.b") == ""  # b is dict, not string


def test_get_translator_en():
    t = get_translator("en")
    assert t("nav.upload") == "Upload"
    assert t("nav.history") == "History"


def test_get_translator_ja():
    t = get_translator("ja")
    assert t("nav.upload") == "アップロード"
    assert t("nav.history") == "\u5c65\u6b74"


def test_get_translator_fallback_to_en():
    """Unknown language should fall back to English."""
    t = get_translator("fr")
    assert t("nav.upload") == "Upload"


def test_get_translator_missing_key_returns_key():
    """Missing key should return the key itself."""
    t = get_translator("en")
    assert t("nonexistent.key") == "nonexistent.key"


def test_all_nav_keys_present():
    t = get_translator("en")
    for key in ["nav.upload", "nav.history", "nav.costs", "nav.settings"]:
        result = t(key)
        assert result != key, f"Key {key} not found in translations"


def test_upload_keys_nonempty():
    """All upload translation values should be non-empty strings."""
    en = _translations["en"]
    for key, value in en["upload"].items():
        assert isinstance(value, str), f"upload.{key} is not a string"
        assert len(value) > 0, f"upload.{key} is empty"


def test_status_keys_cover_all_statuses():
    """Status translations should cover all job statuses."""
    expected = ["pending", "extracting", "transcribing", "refining", "generating_metadata", "completed", "failed"]
    for lang in ("en", "ja"):
        for status in expected:
            assert status in _translations[lang]["status"], f"status.{status} missing in {lang}"
