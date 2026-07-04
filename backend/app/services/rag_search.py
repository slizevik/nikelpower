"""RAG-поиск по DocumentChunk в Neo4j."""

from __future__ import annotations

from dataclasses import dataclass

from app.dictionary.embeddings import embed_text
from app.ingestion.chunk_store import DocumentChunkStore


@dataclass
class RagHit:
    chunk_id: str
    text: str
    score: float
    source_path: str | None
    page_start: int | None
    page_end: int | None
    document_category: str | None
    document_title: str | None


class RagSearchService:
    def __init__(self, chunk_store: DocumentChunkStore | None = None) -> None:
        self.chunk_store = chunk_store or DocumentChunkStore()

    def search(
        self,
        query: str,
        top_k: int = 5,
        group_id: str | None = None,
    ) -> list[RagHit]:
        self.chunk_store.ensure_schema()
        vector = embed_text(query)
        rows = self.chunk_store.search_chunks(vector, top_k=top_k, group_id=group_id)
        hits: list[RagHit] = []
        for row in rows:
            hits.append(
                RagHit(
                    chunk_id=row.get("chunk_id", ""),
                    text=row.get("text", ""),
                    score=float(row.get("score", 0)),
                    source_path=row.get("source_path"),
                    page_start=row.get("page_start"),
                    page_end=row.get("page_end"),
                    document_category=row.get("document_category"),
                    document_title=row.get("document_title"),
                )
            )
        return hits

    def build_context(self, query: str, top_k: int = 5) -> str:
        hits = self.search(query, top_k=top_k)
        if not hits:
            return ""
        parts = []
        for i, hit in enumerate(hits, 1):
            header = f"[{i}] {hit.document_title or hit.source_path} (score={hit.score:.3f})"
            parts.append(f"{header}\n{hit.text}")
        return "\n\n---\n\n".join(parts)
