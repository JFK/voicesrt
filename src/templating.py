import json
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

_i18n_dir = Path(__file__).parent / "i18n"
_translations: dict[str, dict] = {}


def _load_translations() -> None:
    for f in _i18n_dir.glob("*.json"):
        lang = f.stem
        _translations[lang] = json.loads(f.read_text("utf-8"))


_load_translations()


def _get_nested(d: dict, key: str, default: str = "") -> str:
    """Get nested value by dot-separated key: 'upload.title' -> d['upload']['title']."""
    for part in key.split("."):
        if isinstance(d, dict):
            d = d.get(part, default)
        else:
            return default
    return d if isinstance(d, str) else default


def get_translator(lang: str):
    """Return a translation function for the given language."""
    translations = _translations.get(lang, _translations.get("en", {}))
    fallback = _translations.get("en", {})

    def t(key: str) -> str:
        result = _get_nested(translations, key)
        return result if result else _get_nested(fallback, key, key)

    return t


def get_lang(request: Request) -> str:
    """Determine language from cookie or Accept-Language header."""
    lang = request.cookies.get("lang")
    if lang in _translations:
        return lang
    accept = request.headers.get("accept-language", "")
    return "ja" if "ja" in accept else "en"


templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
