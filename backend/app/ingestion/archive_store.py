"""Архивирование исходного файла документа."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.config import settings


def archive_original_document(source_path: Path, group_id: str) -> Path:
    source_path = source_path.resolve()
    archive_root = settings.documents_dir / "archive" / group_id
    archive_root.mkdir(parents=True, exist_ok=True)
    dest = archive_root / source_path.name
    shutil.copy2(source_path, dest)
    return dest
