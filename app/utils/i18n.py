"""Tiny i18n helper. Loads app/locales/*.json once and exposes `t(lang, key,
**kwargs)`. Falls back to DEFAULT_LANGUAGE, then to the key itself, so a
missing translation never crashes a handler."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.config.settings import settings

_LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"


@lru_cache
def _load_all() -> dict[str, dict[str, str]]:
    catalogs: dict[str, dict[str, str]] = {}
    for path in _LOCALES_DIR.glob("*.json"):
        catalogs[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return catalogs


def available_languages() -> list[str]:
    return sorted(_load_all().keys())


def t(lang: str | None, key: str, **kwargs) -> str:
    catalogs = _load_all()
    lang = lang if lang in catalogs else settings.DEFAULT_LANGUAGE
    catalog = catalogs.get(lang) or catalogs.get(settings.DEFAULT_LANGUAGE, {})
    template = catalog.get(key)
    if template is None:
        template = catalogs.get(settings.DEFAULT_LANGUAGE, {}).get(key, key)
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template
