"""Очистка текста RAG-фрагментов и summary от артефактов ingestion."""

from __future__ import annotations

import re

_FIGURE_MARKER = re.compile(r"\[FIGURE\s+[^\]]+\]:\s*", re.IGNORECASE)
_IMG_MARKER = re.compile(r"\[IMG:[^\]]+\]", re.IGNORECASE)
_JSON_FENCE = re.compile(r"```(?:json)?\s*[\s\S]*?```", re.IGNORECASE)
_JSON_OBJECT = re.compile(r"\{\s*\"image_type\"\s*:[\s\S]*?\}", re.IGNORECASE)
_TRUNCATED_JSON = re.compile(r"\{\s*\"image_type\"\s*:[\s\S]*$", re.IGNORECASE)
_MULTI_SPACE = re.compile(r"\s+")


def sanitize_rag_text(text: str) -> str:
    """Убирает маркеры изображений и сырой JSON из текста чанков."""
    if not text:
        return ""

    cleaned = _FIGURE_MARKER.sub(" ", text)
    cleaned = _IMG_MARKER.sub(" ", cleaned)
    cleaned = _JSON_FENCE.sub(" ", cleaned)
    cleaned = _JSON_OBJECT.sub(" ", cleaned)
    cleaned = _TRUNCATED_JSON.sub(" ", cleaned)
    cleaned = _MULTI_SPACE.sub(" ", cleaned).strip()
    return cleaned


def sanitize_summary(text: str, *, max_words: int = 150) -> str:
    """Очищает summary и ограничивает длину."""
    cleaned = sanitize_rag_text(text or "")
    cleaned = cleaned.strip(" \"'")
    if not cleaned:
        return ""
    return truncate_words(cleaned, max_words=max_words)


def truncate_words(text: str, *, max_words: int = 150) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    trimmed = " ".join(words[:max_words]).rstrip(".,;:-")
    return f"{trimmed}…"
