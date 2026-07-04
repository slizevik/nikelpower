#!/usr/bin/env python3
"""CLI: полный парсинг документа (LibreOffice → PDF → VLM)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("parse_document")


def main() -> int:
    parser = argparse.ArgumentParser(description="Парсинг PDF/DOCX/PPTX")
    parser.add_argument("path", type=Path, help="Путь к документу")
    parser.add_argument("--no-vlm", action="store_true", help="Без Qwen-VL (только текст)")
    parser.add_argument("--json", action="store_true", help="Вывод image_descriptions как JSON")
    args = parser.parse_args()

    from app.ingestion.orchestrator import parse_document_full

    try:
        result = parse_document_full(args.path, analyze_images=not args.no_vlm)
    except Exception as exc:
        logger.error("%s", exc)
        return 1

    print(f"Источник:   {result.source_path}")
    print(f"PDF:        {result.pdf_path}")
    print(f"Страниц:    {len(result.pages)}")
    print(f"Изображений:{len(result.images)}")
    if args.json:
        print(json.dumps(result.image_descriptions, ensure_ascii=False, indent=2))
    else:
        for img_id, desc in result.image_descriptions.items():
            print(f"\n[{img_id}]\n{desc[:500]}")
    print(f"\n--- Текст (фрагмент) ---\n{result.text_with_descriptions()[:1500]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
