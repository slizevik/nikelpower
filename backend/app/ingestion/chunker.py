"""Paragraph-aware chunking для RAG (~850 tokens)."""

from __future__ import annotations

import hashlib

from app.config import settings
from app.ingestion.lexical import BlockType, ParagraphBlock
from app.ingestion.paragraphs import document_to_blocks
from app.ingestion.parser_types import ParsedDocument
from app.llm.token_budget import clip_text_to_token_limit, count_tokens
from app.models.chunk import TextChunk


def _split_text_for_chunks(text: str, max_tokens: int) -> list[str]:
    if count_tokens(text) <= max_tokens:
        return [text]

    parts: list[str] = []
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    buffer: list[str] = []

    def flush_buffer() -> None:
        nonlocal buffer
        if not buffer:
            return
        joined = "\n\n".join(buffer)
        if count_tokens(joined) > max_tokens:
            parts.append(clip_text_to_token_limit(joined, max_tokens))
        else:
            parts.append(joined)
        buffer = []

    for para in paragraphs:
        trial = "\n\n".join(buffer + [para]) if buffer else para
        if buffer and count_tokens(trial) > max_tokens:
            flush_buffer()
        if count_tokens(para) > max_tokens:
            flush_buffer()
            parts.append(clip_text_to_token_limit(para, max_tokens))
            continue
        buffer.append(para)

    flush_buffer()
    return parts or [clip_text_to_token_limit(text, max_tokens)]


def file_group_id(source_path: str) -> str:
    normalized = source_path.replace("\\", "/")
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def chunk_document(doc: ParsedDocument, *, group_id: str | None = None) -> list[TextChunk]:
    blocks = document_to_blocks(doc)
    if not blocks:
        return []

    group_id = group_id or file_group_id(doc.source_path)
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
        for part in _split_text_for_chunks(text, max_tokens):
            _emit_chunk_part(
                chunks,
                doc=doc,
                group_id=group_id,
                chunk_index_ref=[chunk_index],
                role=role,
                group=group,
                text=part,
            )
            chunk_index += 1

    def _emit_chunk_part(
        chunks_out: list[TextChunk],
        *,
        doc: ParsedDocument,
        group_id: str,
        chunk_index_ref: list[int],
        role: BlockType,
        group: list[ParagraphBlock],
        text: str,
    ) -> None:
        idx = chunk_index_ref[0]
        tokens = count_tokens(text)
        page_start = min(b.page for b in group)
        page_end = max(b.page for b in group)
        section = next((b.section_hint for b in reversed(group) if b.section_hint), None)
        chunk_id = hashlib.sha256(
            f"{doc.source_path}:{idx}:{group[0].block_id}:{text[:80]}".encode()
        ).hexdigest()[:16]
        chunks_out.append(
            TextChunk(
                chunk_id=chunk_id,
                source_path=doc.source_path,
                doc_type=doc.doc_type,
                language_hint=doc.language_hint,
                page_start=page_start,
                page_end=page_end,
                chunk_index=idx,
                text=text,
                group_id=group_id,
                chunk_role=role,
                block_ids=[b.block_id for b in group],
                token_count=tokens,
                section_hint=section,
            )
        )

    def flush_body() -> list[ParagraphBlock]:
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
