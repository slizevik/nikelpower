#!/usr/bin/env python3
"""CLI: извлечение сущностей из prepared_document.txt."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract entities from prepared document")
    parser.add_argument("prepared_file", type=Path, help="Path to prepared_document.txt")
    parser.add_argument("--category", default="other", help="Document category id")
    parser.add_argument("--source", default="", help="Original source path")
    args = parser.parse_args()

    if not args.prepared_file.exists():
        print(f"File not found: {args.prepared_file}", file=sys.stderr)
        return 1

    try:
        from app.ingestion.entity_extractor import (
            extract_entities_from_prepared_file,
            save_extraction_result,
        )

        source = args.source or str(args.prepared_file)
        result = extract_entities_from_prepared_file(
            args.prepared_file,
            source_path=source,
            document_category=args.category,
        )
        out = save_extraction_result(result, args.prepared_file)
        print(f"Entities: {result.entity_count}, Relations: {result.relation_count}")
        print(f"Saved: {out}")
        print(f"Prompt: {result.prompt_source}")
        return 0
    except Exception as exc:
        logging.exception("Extraction failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
