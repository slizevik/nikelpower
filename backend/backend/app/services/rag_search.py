"""RAG-поиск по DocumentChunk в Neo4j (косинусная близость)."""

from __future__ import annotations

from dataclasses import dataclass

from app.dictionary.embeddings import embed_text
from app.ingestion.chunk_store import DocumentChunkStore
from app.ingestion.entity_store import IngestedEntityStore
from app.models.chat import ChatSearchFilters


@dataclass
class RagHit:
    chunk_id: str
    text: str
    score: float
    source_path: str | None
    page_start: int | None
    page_end: int | None
    group_id: str | None
    document_category: str | None
    document_title: str | None
    updated_at: str | None = None
    original_storage_path: str | None = None


class RagSearchService:
    def __init__(
        self,
        chunk_store: DocumentChunkStore | None = None,
        entity_store: IngestedEntityStore | None = None,
    ) -> None:
        self.chunk_store = chunk_store or DocumentChunkStore()
        self.entity_store = entity_store or IngestedEntityStore()

    def search(
        self,
        query: str,
        top_k: int = 5,
        group_id: str | None = None,
        *,
        filters: ChatSearchFilters | None = None,
        fetch_multiplier: int = 5,
    ) -> list[RagHit]:
        self.chunk_store.ensure_schema()
        vector = embed_text(query)

        fetch_k = top_k * fetch_multiplier if filters else top_k
        rows = self.chunk_store.search_chunks(vector, top_k=fetch_k, group_id=group_id)

        if filters:
            rows = self._apply_filters(rows, filters)

        hits: list[RagHit] = []
        for row in rows[:top_k]:
            hits.append(
                RagHit(
                    chunk_id=row.get("chunk_id", ""),
                    text=row.get("text", ""),
                    score=float(row.get("score", 0)),
                    source_path=row.get("source_path"),
                    page_start=row.get("page_start"),
                    page_end=row.get("page_end"),
                    group_id=row.get("group_id"),
                    document_category=row.get("document_category"),
                    document_title=row.get("document_title"),
                    updated_at=row.get("updated_at"),
                    original_storage_path=row.get("original_storage_path"),
                )
            )
        return hits

    def _apply_filters(self, rows: list[dict], filters: ChatSearchFilters) -> list[dict]:
        allowed_groups = self._resolve_geo_group_ids(filters)
        if allowed_groups is not None:
            if not allowed_groups:
                return []
            allowed_set = set(allowed_groups)
            rows = [r for r in rows if r.get("group_id") in allowed_set]

        if filters.document_category and filters.document_category not in ("", "all"):
            rows = [
                r
                for r in rows
                if (r.get("document_category") or "") == filters.document_category
            ]

        if filters.min_relevance_score > 0:
            rows = [r for r in rows if float(r.get("score", 0)) >= filters.min_relevance_score]

        return rows

    def _resolve_geo_group_ids(self, filters: ChatSearchFilters) -> list[str] | None:
        if filters.include_domestic and filters.include_foreign:
            return None
        if not filters.include_domestic and not filters.include_foreign:
            return None
        if filters.include_domestic:
            return self.entity_store.find_group_ids_by_geo("russia")
        return self.entity_store.find_group_ids_by_geo("foreign")

    def group_hits_by_document(self, hits: list[RagHit]) -> dict[str, list[RagHit]]:
        grouped: dict[str, list[RagHit]] = {}
        for hit in hits:
            key = hit.group_id or hit.source_path or hit.chunk_id
            grouped.setdefault(key, []).append(hit)
        for key in grouped:
            grouped[key].sort(key=lambda h: h.score, reverse=True)
        return grouped

    def build_context(self, query: str, top_k: int = 5) -> str:
        hits = self.search(query, top_k=top_k)
        if not hits:
            return ""
        parts = []
        for i, hit in enumerate(hits, 1):
            header = f"[{i}] {hit.document_title or hit.source_path} (score={hit.score:.3f})"
            parts.append(f"{header}\n{hit.text}")
        return "\n\n---\n\n".join(parts)
