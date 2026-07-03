"""
Пайплайн загрузки PDF в Neo4j: парсинг → чанки (15% overlap) → эмбеддинги → граф.

Используется для документов из data/documents/pilot и других каталогов.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import settings
from app.dictionary.embeddings import embed_texts
from app.dictionary.store import EntityDictionaryStore
from app.ingestion.chunk_store import DocumentChunkStore, IngestStats
from app.ingestion.chunker import TextChunk, chunk_document, file_group_id
from app.ingestion.parser import parse_document

logger = logging.getLogger(__name__)


class PdfIngestionPipeline:
    """
    Полный цикл обработки одного PDF-файла:
    1. Извлечение текста
    2. Разбиение на чанки с перекрытием (по умолчанию 15%)
    3. Векторизация через Yandex embeddings API
    4. Сохранение узлов SourceDocument и DocumentChunk в Neo4j
    """

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

    def ingest_pdf(self, pdf_path: Path) -> IngestStats:
        pdf_path = pdf_path.resolve()
        if not pdf_path.exists():
            raise FileNotFoundError(f"Файл не найден: {pdf_path}")
        if pdf_path.suffix.lower() != ".pdf":
            raise ValueError(f"Ожидается PDF, получено: {pdf_path.suffix}")

        logger.info("Парсинг PDF: %s", pdf_path)
        parsed = parse_document(pdf_path)

        if not parsed.full_text.strip():
            raise ValueError(
                f"PDF не содержит извлекаемого текста (возможно скан): {pdf_path.name}"
            )

        chunks = chunk_document(parsed)
        if not chunks:
            raise ValueError(f"Не удалось создать чанки для {pdf_path.name}")

        overlap = settings.effective_chunk_overlap_chars
        logger.info(
            "Создано %s чанков (size=%s, overlap=%s, %.0f%%)",
            len(chunks),
            settings.chunk_size_chars,
            overlap,
            settings.chunk_overlap_percent,
        )

        self.chunk_store.ensure_schema()
        self.dict_store.ensure_schema()

        group_id = file_group_id(str(pdf_path))
        self.chunk_store.upsert_source_document(
            source_path=str(pdf_path),
            group_id=group_id,
            doc_type=parsed.doc_type,
            language_hint=parsed.language_hint,
            chunks_count=len(chunks),
        )

        saved_total = self._vectorize_and_save(chunks)

        return IngestStats(
            source_path=str(pdf_path),
            group_id=group_id,
            chunks_total=len(chunks),
            chunks_saved=saved_total,
            document_node_created=True,
        )

    def _vectorize_and_save(self, chunks: list[TextChunk]) -> int:
        batch_size = max(1, settings.ingestion_batch_size)
        saved = 0

        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            texts = [c.text for c in batch]

            logger.info(
                "Эмбеддинги: батч %s–%s из %s",
                start + 1,
                start + len(batch),
                len(chunks),
            )
            vectors = embed_texts(texts)
            saved += self.chunk_store.save_chunk_batch(batch, vectors)

        return saved


def ingest_pilot_pdfs(pilot_dir: Path | None = None) -> list[IngestStats]:
    """Обрабатывает все PDF из каталога pilot."""
    root = pilot_dir or (settings.documents_dir / "pilot")
    root = root.resolve()

    if not root.is_dir():
        raise FileNotFoundError(f"Каталог pilot не найден: {root}")

    pdf_files = sorted(root.glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError(f"В {root} нет PDF-файлов")

    pipeline = PdfIngestionPipeline()
    results: list[IngestStats] = []

    try:
        for pdf_path in pdf_files:
            logger.info("=== Обработка: %s ===", pdf_path.name)
            stats = pipeline.ingest_pdf(pdf_path)
            results.append(stats)
            logger.info(
                "Готово: %s чанков сохранено для %s",
                stats.chunks_saved,
                pdf_path.name,
            )
    finally:
        pipeline.close()

    return results
