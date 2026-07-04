"""Lexical graph: paragraph blocks, типы (body, caption, table, heading)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

BlockType = Literal["body", "caption", "table", "heading"]

CAPTION_PATTERN = re.compile(
    r"^(?:Рис\.?|Рисунок|Fig\.?|Figure|Схема|Illustration)\s*[\d\.]+",
    re.IGNORECASE,
)
TABLE_PATTERN = re.compile(
    r"^(?:Таблица|Table)\s*[\d\.]+",
    re.IGNORECASE,
)
HEADING_PATTERN = re.compile(
    r"^(?:\d+(?:\.\d+)*[\.\)]\s+|[IVXLC]+\.\s+)",
)


@dataclass
class ParagraphBlock:
    block_id: str
    page: int
    order_index: int
    text: str
    block_type: BlockType
    section_hint: str | None = None


def make_block_id(source_path: str, order_index: int) -> str:
    key = f"{source_path.replace(chr(92), '/')}:{order_index}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def detect_block_type(text: str) -> BlockType:
    stripped = text.strip()
    if not stripped:
        return "body"
    first_line = stripped.split("\n", 1)[0].strip()
    if CAPTION_PATTERN.match(first_line):
        return "caption"
    if TABLE_PATTERN.match(first_line):
        return "table"
    if len(first_line) < 120 and HEADING_PATTERN.match(first_line):
        return "heading"
    if len(stripped) < 80 and stripped.isupper() and " " in stripped:
        return "heading"
    return "body"


def split_page_paragraphs(page_text: str) -> list[str]:
    parts = re.split(r"\n\s*\n+", page_text.strip())
    return [p.strip() for p in parts if p.strip()]
