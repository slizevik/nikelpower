"""Text chunk model for Graphiti ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TextChunk:
    chunk_id: str
    source_path: str
    doc_type: str
    language_hint: str
    page_start: int
    page_end: int
    chunk_index: int
    text: str
    group_id: str
    chunk_role: str = "body"
    block_ids: list[str] = field(default_factory=list)
    token_count: int = 0
    section_hint: str | None = None
