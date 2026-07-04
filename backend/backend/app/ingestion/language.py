"""Определение языка текста документа."""

from __future__ import annotations

import re


def detect_language_hint(text: str) -> str:
    cyrillic = len(re.findall(r"[а-яА-ЯёЁ]", text))
    latin = len(re.findall(r"[a-zA-Z]", text))
    if cyrillic > latin * 1.5:
        return "ru"
    if latin > cyrillic * 1.5:
        return "en"
    return "mixed"
