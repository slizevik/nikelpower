"""Валидация загружаемых документов."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.ingestion.exceptions import SUPPORTED_DOCUMENT_EXTENSIONS, UnsupportedFormatError


@dataclass
class ValidationResult:
    ok: bool
    message: str
    supported: tuple[str, ...]


def validate_upload(path: Path) -> ValidationResult:
    ext = path.suffix.lower()
    supported = tuple(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
    if ext in SUPPORTED_DOCUMENT_EXTENSIONS:
        return ValidationResult(ok=True, message="", supported=supported)
    labels = ", ".join(e.lstrip(".") for e in supported).upper()
    return ValidationResult(
        ok=False,
        message=f"Загрузите документ нужного формата: {labels}.",
        supported=supported,
    )


def require_supported(path: Path) -> None:
    ext = path.suffix.lower()
    if ext not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise UnsupportedFormatError(str(path), ext)
