"""Сохранение загруженных файлов и метаданных категории."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings


@dataclass
class UploadMeta:
    upload_id: str
    original_name: str
    saved_path: str
    category: str
    uploaded_at: str
    size_bytes: int


def uploads_dir() -> Path:
    root = settings.documents_dir / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_uploaded_file(file_bytes: bytes, original_name: str, category: str) -> UploadMeta:
    upload_id = uuid.uuid4().hex[:12]
    safe_name = Path(original_name).name
    dest = uploads_dir() / f"{upload_id}_{safe_name}"
    dest.write_bytes(file_bytes)

    meta = UploadMeta(
        upload_id=upload_id,
        original_name=safe_name,
        saved_path=str(dest),
        category=category,
        uploaded_at=datetime.now(timezone.utc).isoformat(),
        size_bytes=len(file_bytes),
    )
    meta_path = uploads_dir() / f"{upload_id}_meta.json"
    meta_path.write_text(json.dumps(asdict(meta), ensure_ascii=False, indent=2), encoding="utf-8")
    return meta
