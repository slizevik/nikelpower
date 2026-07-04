"""Сохранение «подготовленного документа» — текста с описаниями изображений."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.config import settings
from app.ingestion.models import ParseResult


def _prepared_dir(source_path: str) -> Path:
    key = hashlib.sha256(source_path.replace("\\", "/").encode()).hexdigest()[:16]
    root = settings.ingestion_state_dir / "prepared" / key
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_raw_text(result: ParseResult) -> Path:
    """Текст с плейсхолдерами [IMG:id] до VLM."""
    root = _prepared_dir(result.source_path)
    path = root / "raw_text.txt"
    path.write_text(result.full_text, encoding="utf-8")
    return path


def save_prepared_document(result: ParseResult) -> Path:
    """Подготовленный документ: текст + описания изображений."""
    root = _prepared_dir(result.source_path)
    path = root / "prepared_document.txt"
    path.write_text(result.text_with_descriptions(), encoding="utf-8")
    meta = root / "meta.txt"
    meta.write_text(
        "\n".join(
            [
                f"source={result.source_path}",
                f"pdf={result.pdf_path}",
                f"doc_type={result.doc_type}",
                f"language={result.language_hint}",
                f"pages={len(result.pages)}",
                f"images={len(result.images)}",
            ]
        ),
        encoding="utf-8",
    )
    return path


def save_parse_snapshot(result: ParseResult) -> Path:
    root = _prepared_dir(result.source_path)
    path = root / "parse_snapshot.json"
    payload = {
        "source_path": result.source_path,
        "doc_type": result.doc_type,
        "pdf_path": result.pdf_path,
        "language_hint": result.language_hint,
        "pages": result.pages,
        "full_text": result.full_text,
        "image_descriptions": result.image_descriptions,
        "prepared_document_path": result.prepared_document_path,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_parse_snapshot(source_path: str) -> ParseResult:
    path = _prepared_dir(source_path) / "parse_snapshot.json"
    if not path.exists():
        raise FileNotFoundError(f"Parse snapshot not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    pages_raw = data.get("pages") or []
    pages = [(int(p[0]), str(p[1])) for p in pages_raw]
    return ParseResult(
        source_path=data["source_path"],
        doc_type=data.get("doc_type", "pdf"),
        pdf_path=data.get("pdf_path", ""),
        language_hint=data.get("language_hint", "unknown"),
        pages=pages,
        full_text=data.get("full_text", ""),
        image_descriptions=data.get("image_descriptions") or {},
        prepared_document_path=data.get("prepared_document_path"),
    )
