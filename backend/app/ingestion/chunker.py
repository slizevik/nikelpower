"""Split parsed documents into overlapping chunks for Graphiti episodes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.config import settings
from app.ingestion.parser import ParsedDocument


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


def file_group_id(source_path: str) -> str:
    normalized = source_path.replace("\\", "/")
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def chunk_document(doc: ParsedDocument) -> list[TextChunk]:
    if not doc.pages:
        return []

    size = settings.chunk_size_chars
    overlap = settings.effective_chunk_overlap_chars
    group_id = file_group_id(doc.source_path)

    chunks: list[TextChunk] = []
    buffer = ""
    page_start = doc.pages[0][0]
    page_end = doc.pages[0][0]
    chunk_index = 0

    def flush() -> None:
        nonlocal buffer, page_start, page_end, chunk_index
        text = buffer.strip()
        if not text:
            return
        chunk_id = hashlib.sha256(
            f"{doc.source_path}:{chunk_index}:{text[:200]}".encode()
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
            )
        )
        chunk_index += 1
        if overlap > 0 and len(text) > overlap:
            buffer = text[-overlap:]
            page_start = page_end
        else:
            buffer = ""
            page_start = page_end

    for page_num, page_text in doc.pages:
        page_end = page_num
        segment = f"\n\n[page {page_num}]\n{page_text}"
        # Ограниченный цикл вместо while True: сегмент уменьшается на каждой итерации
        max_iterations = max(1, len(segment) // max(1, size - overlap) + 2)
        for _ in range(max_iterations):
            if not segment:
                break
            space = size - len(buffer)
            if len(segment) <= space:
                buffer += segment
                segment = ""
            else:
                buffer += segment[:space]
                segment = segment[space:]
                flush()
        else:
            raise RuntimeError(
                f"chunk_document: превышен лимит итераций ({max_iterations}) "
                f"для {doc.source_path}"
            )

    if buffer.strip():
        flush()

    return chunks
