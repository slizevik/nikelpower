"""
AI-агент вкладки «Чат с LLM».

1. Дополняет запрос фильтрами Frontend
2. Векторный поиск (косинусная близость) по DocumentChunk
3. Формирует структурированный список документов через LLM
"""

from __future__ import annotations

import json
import logging

from app.config import settings
from app.ingestion.entity_store import IngestedEntityStore
from app.llm.tracked_api import chat_completions_create
from app.llm.yandex_client import get_yandex_client
from app.models.chat import ChatAgentResponse, ChatDocumentResult, ChatSearchFilters
from app.services.query_augmentation import augment_query
from app.services.rag_search import RagHit, RagSearchService
from app.services.text_cleanup import sanitize_rag_text, sanitize_summary

logger = logging.getLogger(__name__)

SUMMARY_MAX_WORDS = 150

SYSTEM_PROMPT = f"""You are a materials-science document retrieval assistant for Nikelpower.
You receive user query and retrieved document fragments from a vector database (cosine similarity).

Rules:
- Answer ONLY based on provided fragments. Do NOT invent documents or authors.
- For each distinct source document, produce one entry in "documents".
- summary: explain how the document relates to the user query in clear Russian prose.
  HARD LIMIT: at most {SUMMARY_MAX_WORDS} words per summary.
  Write 2–4 complete sentences. No bullet lists, no markdown, no code blocks.
  NEVER copy or paraphrase ingestion artifacts: [FIGURE ...], [IMG:...], UUIDs, ```json blocks, raw JSON keys like "image_type", truncated VLM output.
  If fragments only contain figure captions or garbage, summarize only the readable scientific content you can infer from other fragments.
- author_or_source: authors, organization, or publication name from fragments; null if unknown.
- updated_at: use provided updated_at from metadata; null if unknown.
- reliability: high (score>=0.82), medium (0.70–0.82), low (<0.70) based on relevance score.
- For comparative queries (A vs B, domestic vs international), fill comparative_note.
- If fragments are empty or irrelevant, set no_data=true and documents=[].
- Respond in Russian unless the user query is in English.
- Output valid JSON only, matching the schema exactly.
"""

SCORE_HIGH = 0.82
SCORE_MEDIUM = 0.70


class ChatAgentService:
    def __init__(
        self,
        rag: RagSearchService | None = None,
        entity_store: IngestedEntityStore | None = None,
    ) -> None:
        self.rag = rag or RagSearchService()
        self.entity_store = entity_store or IngestedEntityStore()

    def search_documents(
        self,
        user_query: str,
        filters: ChatSearchFilters | None = None,
        *,
        top_k: int = 15,
    ) -> ChatAgentResponse:
        filters = filters or ChatSearchFilters()
        augmented = augment_query(user_query, filters)

        if self._is_comparative(user_query):
            return self._comparative_search(user_query, filters, top_k=top_k)

        hits = self.rag.search(augmented, top_k=top_k, filters=filters, fetch_multiplier=6)

        if filters.min_relevance_score <= 0:
            hits = [h for h in hits if h.score >= settings.embedding_similarity_threshold * 0.85]

        if not hits:
            return ChatAgentResponse(
                query=user_query,
                augmented_query=augmented,
                filters_applied=filters,
                documents=[],
                no_data=True,
                message="По вашему запросу не найдено ни одного релевантного источника в базе данных.",
            )

        grouped = self.rag.group_hits_by_document(hits)
        return self._build_response(user_query, augmented, filters, grouped)

    def _comparative_search(
        self,
        user_query: str,
        filters: ChatSearchFilters,
        *,
        top_k: int,
    ) -> ChatAgentResponse:
        """Сравнительные запросы: отдельный поиск для каждой стороны."""
        sides = self._split_comparative_query(user_query)
        if len(sides) < 2:
            return self.search_documents(user_query, filters, top_k=top_k)

        all_docs: list[ChatDocumentResult] = []
        notes: list[str] = []

        for i, side in enumerate(sides[:2], 1):
            side_filters = filters.model_copy()
            side_query = f"{side.strip()}. {user_query}"
            augmented = augment_query(side_query, side_filters)
            hits = self.rag.search(augmented, top_k=top_k // 2 + 1, filters=side_filters, fetch_multiplier=4)
            if hits:
                grouped = self.rag.group_hits_by_document(hits)
                partial = self._build_response(
                    side_query,
                    augmented,
                    side_filters,
                    grouped,
                    skip_llm_note=True,
                )
                for doc in partial.documents:
                    doc.summary = f"[Сторона {i}] {doc.summary}"
                all_docs.extend(partial.documents)
                notes.append(f"Сторона {i} («{side.strip()}»): найдено {len(partial.documents)} док.")
            else:
                notes.append(f"Сторона {i} («{side.strip()}»): данных не найдено.")

        if not all_docs:
            return ChatAgentResponse(
                query=user_query,
                augmented_query=augment_query(user_query, filters),
                filters_applied=filters,
                documents=[],
                no_data=True,
                message="По сравнительному запросу не найдено источников ни для одной из сторон.",
                comparative_note="; ".join(notes),
            )

        return ChatAgentResponse(
            query=user_query,
            augmented_query=augment_query(user_query, filters),
            filters_applied=filters,
            documents=all_docs,
            no_data=False,
            message=f"Найдено документов: {len(all_docs)}",
            comparative_note="; ".join(notes),
        )

    def _build_response(
        self,
        user_query: str,
        augmented: str,
        filters: ChatSearchFilters,
        grouped: dict[str, list[RagHit]],
        *,
        skip_llm_note: bool = False,
    ) -> ChatAgentResponse:
        doc_blocks = []
        for group_id, doc_hits in grouped.items():
            meta = doc_hits[0]
            authors = self.entity_store.get_authors_for_document(group_id) if group_id else []
            author_str = ", ".join(authors) if authors else None
            pages = f"{meta.page_start}–{meta.page_end}" if meta.page_start else None
            clean_parts: list[str] = []
            for h in doc_hits[:3]:
                cleaned = sanitize_rag_text(h.text)[:1200]
                if cleaned:
                    clean_parts.append(cleaned)
            fragments = "\n\n".join(clean_parts)
            doc_blocks.append(
                {
                    "group_id": group_id,
                    "title": meta.document_title or meta.source_path or "Без названия",
                    "document_category": meta.document_category,
                    "author_or_source": author_str,
                    "updated_at": meta.updated_at,
                    "download_path": meta.original_storage_path,
                    "max_score": max(h.score for h in doc_hits),
                    "pages": pages,
                    "fragments": fragments,
                }
            )

        llm_docs = self._summarize_with_llm(user_query, doc_blocks)

        documents: list[ChatDocumentResult] = []
        for i, block in enumerate(doc_blocks):
            llm_item = llm_docs[i] if i < len(llm_docs) else {}
            score = float(block.get("max_score", 0))
            raw_summary = llm_item.get("summary") or block["fragments"][:400]
            summary = sanitize_summary(raw_summary, max_words=SUMMARY_MAX_WORDS) or sanitize_summary(
                block["fragments"], max_words=SUMMARY_MAX_WORDS
            )
            documents.append(
                ChatDocumentResult(
                    title=llm_item.get("title") or block["title"],
                    summary=summary,
                    author_or_source=llm_item.get("author_or_source") or block.get("author_or_source"),
                    updated_at=llm_item.get("updated_at") or block.get("updated_at"),
                    download_path=block.get("download_path"),
                    group_id=block.get("group_id"),
                    document_category=block.get("document_category"),
                    relevance_score=round(score, 4),
                    matched_pages=block.get("pages"),
                    reliability=_reliability_label(score),
                )
            )

        documents.sort(key=lambda d: d.relevance_score, reverse=True)

        return ChatAgentResponse(
            query=user_query,
            augmented_query=augmented,
            filters_applied=filters,
            documents=documents,
            no_data=False,
            message=f"Найдено документов: {len(documents)}",
        )

    def _summarize_with_llm(self, user_query: str, doc_blocks: list[dict]) -> list[dict]:
        if not settings.yandex_cloud_model:
            return [
                {
                    "title": b["title"],
                    "summary": sanitize_summary(b["fragments"], max_words=SUMMARY_MAX_WORDS),
                }
                for b in doc_blocks
            ]

        context = json.dumps(doc_blocks, ensure_ascii=False, indent=2)
        user_prompt = f"""User query: {user_query}

Retrieved documents (fragments from vector DB, cosine similarity):
{context}

Return JSON:
{{
  "documents": [
    {{
      "title": "string",
      "summary": "string — relevance to user query, Russian, max 150 words, no figure/json artifacts",
      "author_or_source": "string or null",
      "updated_at": "string or null"
    }}
  ],
  "no_data": false,
  "comparative_note": null
}}
"""

        try:
            client = get_yandex_client()
            response = chat_completions_create(
                client,
                model=settings.yandex_cloud_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            raw = response.choices[0].message.content or "{}"
            parsed = json.loads(raw)
            docs = parsed.get("documents") or []
            for item in docs:
                if isinstance(item, dict) and item.get("summary"):
                    item["summary"] = sanitize_summary(
                        str(item["summary"]),
                        max_words=SUMMARY_MAX_WORDS,
                    )
            return docs
        except Exception as exc:
            logger.warning("LLM summarization failed: %s", exc)
            return [
                {
                    "title": b["title"],
                    "summary": sanitize_summary(b["fragments"], max_words=SUMMARY_MAX_WORDS),
                }
                for b in doc_blocks
            ]

    @staticmethod
    def _is_comparative(query: str) -> bool:
        q = query.lower()
        markers = (" vs ", " versus ", " против ", " сравни", " сравнение ", " отечественн", " миров")
        return any(m in q for m in markers)

    @staticmethod
    def _split_comparative_query(query: str) -> list[str]:
        for sep in (" vs ", " versus ", " против ", " / "):
            if sep in query.lower():
                idx = query.lower().index(sep)
                left = query[:idx]
                right = query[idx + len(sep) :]
                return [left, right]
        return [query]


def _reliability_label(score: float) -> str:
    if score >= SCORE_HIGH:
        return "high"
    if score >= SCORE_MEDIUM:
        return "medium"
    return "low"
