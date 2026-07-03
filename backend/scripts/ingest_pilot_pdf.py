#!/usr/bin/env python3
"""
Загрузка PDF из data/documents/pilot в Neo4j.

Шаги: парсинг → чанки (перекрытие 15%) → эмбеддинги Yandex → DocumentChunk.

Пример:
    cd backend
    set PYTHONPATH=.
    python scripts/ingest_pilot_pdf.py

В Docker:
    docker compose exec backend python scripts/ingest_pilot_pdf.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ingest_pilot_pdf")


def main() -> int:
    from app.config import settings
    from app.ingestion.pdf_pipeline import ingest_pilot_pdfs

    pilot_dir = settings.documents_dir / "pilot"
    logger.info("Каталог pilot: %s", pilot_dir)
    logger.info(
        "Параметры чанков: size=%s, overlap=%s симв. (%.0f%%)",
        settings.chunk_size_chars,
        settings.effective_chunk_overlap_chars,
        settings.chunk_overlap_percent,
    )

    try:
        results = ingest_pilot_pdfs(pilot_dir)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:
        logger.exception("Ошибка загрузки: %s", exc)
        return 1

    print("\n=== Результат загрузки ===")
    for item in results:
        print(f"  Файл:     {Path(item.source_path).name}")
        print(f"  group_id: {item.group_id}")
        print(f"  Чанков:   {item.chunks_saved} / {item.chunks_total}")
        print()

    print("Проверка в Neo4j Browser:")
    print("  MATCH (d:SourceDocument)-[:HAS_CHUNK]->(c) RETURN d.source_path, count(c)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
