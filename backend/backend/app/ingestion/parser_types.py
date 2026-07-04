"""Тип ParsedDocument (отдельно от parser.py для избежания циклических импортов)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ParsedDocument:
    source_path: str
    doc_type: str
    language_hint: str
    pages: list[tuple[int, str]]
    full_text: str
