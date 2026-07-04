#!/usr/bin/env python3
"""
CLI: полный парсинг документа (LibreOffice → PDF → VLM).

Пример:
    python scripts/parse_document.py path/to/file.pdf
    python scripts/parse_document.py path/to/file.docx --no-vlm
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("parse_document")


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse document for Nikelpower ingestion")
    parser.add_argument("path", type=Path, help="PDF, DOCX or PPTX file")
    parser.add_argument("--no-vlm", action="store_true", help="Skip Qwen-VL image analysis")
    args = parser.parse_args()

    if not args.path.exists():
        logger.error("File not found: %s", args.path)
        return 1

    def on_progress(step: str, message: str) -> None:
        print(f"  → {message}")

    try:
        from app.ingestion.orchestrator import parse_document_full

        print(f"Parsing: {args.path}")
        result = parse_document_full(
            args.path,
            analyze_images=not args.no_vlm,
            on_progress=on_progress,
        )
        print(f"\nPages: {len(result.pages)}")
        print(f"Images: {len(result.images)}")
        print(f"Language: {result.language_hint}")
        print(f"Prepared document: {result.prepared_document_path}")
        print(f"\nPreview (500 chars):\n{result.text_with_descriptions()[:500]}...")
        return 0
    except Exception as exc:
        logger.exception("Parse failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
