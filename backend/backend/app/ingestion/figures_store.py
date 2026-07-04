"""Сохранение извлечённых изображений на диск (audit / повторный VLM)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.config import settings
from app.ingestion.models import DocumentImage, ParseResult


def _doc_figures_dir(source_path: str) -> Path:
    key = hashlib.sha256(source_path.replace("\\", "/").encode()).hexdigest()[:16]
    root = settings.ingestion_state_dir / "figures" / key
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_document_images(result: ParseResult) -> Path:
    root = _doc_figures_dir(result.source_path)
    for image in result.images:
        ext = "png"
        if "jpeg" in image.mime or "jpg" in image.mime:
            ext = "jpg"
        path = root / f"{image.image_id}.{ext}"
        path.write_bytes(image.data)
    return root
