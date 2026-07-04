"""Paragraph-aware chunking: ~850 tokens, caption/table — отдельные чанки."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from app.config import settings
from app.ingestion.lexical import BlockType, ParagraphBlock
from app.ingestion.paragraphs import document_to_blocks
from app.ingestion.parser import ParsedDocument
from app.llm.token_budget import count_tokens


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
    chunk_role: BlockType = "body"
    block_ids: list[str] = field(default_factory=list)
    token_count: int = 0
    section_hint: str | None = None


def file_group_id(source_path: str) -> str:
    normalized = source_path.replace("\\", "/")
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def chunk_document(doc: ParsedDocument) -> list[TextChunk]:
    blocks = document_to_blocks(doc)
    if not blocks:
        return []

    group_id = file_group_id(doc.source_path)
    target = settings.chunk_target_tokens
    max_tokens = settings.chunk_max_tokens
    overlap_n = settings.chunk_overlap_paragraphs

    chunks: list[TextChunk] = []
    buffer: list[ParagraphBlock] = []
    chunk_index = 0

    def emit(role: BlockType, group: list[ParagraphBlock]) -> None:
        nonlocal chunk_index
        if not group:
            return
        text = "\n\n".join(b.text for b in group)
        tokens = count_tokens(text)
        page_start = min(b.page for b in group)
        page_end = max(b.page for b in group)
        section = next((b.section_hint for b in reversed(group) if b.section_hint), None)
        chunk_id = hashlib.sha256(
            f"{doc.source_path}:{chunk_index}:{group[0].block_id}".encode()
        ).hexdigest()[:16]
        chunks.append(
            TextChunk(
                chunk_id=chunk_id,
                source_path=doc.source_path,
                doc_type=doc.doc_type,
                language_hint=doc.language_hint,
                page_start=page_start,
                page_end=page_end,
                chunk_index=chunk_index,
                text=text,
                group_id=group_id,
                chunk_role=role,
                block_ids=[b.block_id for b in group],
                token_count=tokens,
                section_hint=section,
            )
        )
        chunk_index += 1

    def flush_body() -> list[ParagraphBlock]:
        """Сохраняет body-чанк и возвращает параграфы для overlap."""
        nonlocal buffer
        if not buffer:
            return []
        emit("body", buffer)
        tail = buffer[-overlap_n:] if overlap_n > 0 else []
        buffer = []
        return tail

    def buffer_tokens() -> int:
        return count_tokens("\n\n".join(b.text for b in buffer))

    for block in blocks:
        if block.block_type in ("caption", "table"):
            tail = flush_body()
            buffer = list(tail)
            emit(block.block_type, [block])
            continue

        trial = buffer + [block]
        trial_tokens = count_tokens("\n\n".join(b.text for b in trial))

        if buffer and trial_tokens > max_tokens:
            tail = flush_body()
            buffer = list(tail)

        buffer.append(block)
        if buffer_tokens() >= target:
            tail = flush_body()
            buffer = list(tail)

    if buffer:
        flush_body()

    return chunks
