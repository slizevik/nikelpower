"""
Пайплайн загрузки документов в Neo4j: парсинг → чанки → эмбеддинги.

Поддерживает PDF, DOCX, PPTX (LibreOffice + Qwen-VL по архитектуре парсинга).
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import settings
from app.dictionary.embeddings import embed_texts
from app.dictionary.store import EntityDictionaryStore
from app.ingestion.chunk_store import DocumentChunkStore, IngestStats
from app.ingestion.chunker import TextChunk, chunk_document, file_group_id
from app.ingestion.exceptions import SUPPORTED_DOCUMENT_EXTENSIONS
from app.ingestion.orchestrator import parse_document_full, to_legacy_parsed_document
from app.ingestion.paragraphs import document_to_blocks

logger = logging.getLogger(__name__)


class DocumentIngestionPipeline:
    """Парсинг документа → paragraph chunks → Yandex embeddings → Neo4j."""

    def __init__(
        self,
        chunk_store: DocumentChunkStore | None = None,
        dict_store: EntityDictionaryStore | None = None,
    ) -> None:
        self.chunk_store = chunk_store or DocumentChunkStore()
        self.dict_store = dict_store or EntityDictionaryStore()
        self._owns_stores = chunk_store is None

    def close(self) -> None:
        if self._owns_stores:
            self.chunk_store.close()
            self.dict_store.close()

    def ingest_document(self, doc_path: Path, *, analyze_images: bool | None = None) -> IngestStats:
        doc_path = doc_path.resolve()
        if not doc_path.exists():
            raise FileNotFoundError(f"Файл не найден: {doc_path}")
        suffix = doc_path.suffix.lower()
        if suffix not in SUPPORTED_DOCUMENT_EXTENSIONS:
            raise ValueError(f"Формат не поддерживается: {suffix}")

        logger.info("Парсинг документа: %s", doc_path.name)
        parse_result = parse_document_full(doc_path, analyze_images=analyze_images)
        parsed = to_legacy_parsed_document(parse_result)

        if not parsed.full_text.strip():
            raise ValueError(f"Документ не содержит текста: {doc_path.name}")

        logger.info(
            "Изображений: %s, описаний VLM: %s, PDF: %s",
            len(parse_result.images),
            len(parse_result.image_descriptions),
            parse_result.pdf_path,
        )

        chunks = chunk_document(parsed)
        if not chunks:
            raise ValueError(f"Не удалось создать чанки для {doc_path.name}")

        blocks = document_to_blocks(parsed)
        logger.info(
            "Чанков: %s (target=%s tok), lexical blocks: %s",
            len(chunks),
            settings.chunk_target_tokens,
            len(blocks),
        )

        self.chunk_store.ensure_schema()
        self.dict_store.ensure_schema()

        group_id = file_group_id(str(doc_path))
        self.chunk_store.upsert_source_document(
            source_path=str(doc_path),
            group_id=group_id,
            doc_type=parsed.doc_type,
            language_hint=parsed.language_hint,
            chunks_count=len(chunks),
        )
        self.chunk_store.upsert_lexical_blocks(group_id, blocks)

        saved_total = self._vectorize_and_save(chunks)
        return IngestStats(
            source_path=str(doc_path),
            group_id=group_id,
            chunks_total=len(chunks),
            chunks_saved=saved_total,
            document_node_created=True,
        )

    def ingest_pdf(self, pdf_path: Path) -> IngestStats:
        return self.ingest_document(pdf_path)

    def _vectorize_and_save(self, chunks: list[TextChunk]) -> int:
        batch_size = max(1, settings.ingestion_batch_size)
        saved = 0
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            vectors = embed_texts([c.text for c in batch])
            saved += self.chunk_store.save_chunk_batch(batch, vectors)
        return saved


# Обратная совместимость
PdfIngestionPipeline = DocumentIngestionPipeline


def ingest_pilot_pdfs(pilot_dir: Path | None = None) -> list[IngestStats]:
    root = pilot_dir or (settings.documents_dir / "pilot")
    root = root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Каталог pilot не найден: {root}")

    files = sorted(
        p for p in root.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_DOCUMENT_EXTENSIONS
    )
    if not files:
        raise FileNotFoundError(f"В {root} нет PDF/DOCX/PPTX")

    pipeline = DocumentIngestionPipeline()
    results: list[IngestStats] = []
    try:
        for doc_path in files:
            logger.info("=== %s ===", doc_path.name)
            results.append(pipeline.ingest_document(doc_path))
    finally:
        pipeline.close()
    return results
