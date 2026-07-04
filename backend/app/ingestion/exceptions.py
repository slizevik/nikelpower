"""Ошибки пайплайна парсинга документов."""

from __future__ import annotations

SUPPORTED_DOCUMENT_EXTENSIONS = frozenset({".pdf", ".docx", ".pptx"})


class UnsupportedFormatError(ValueError):
    """Формат файла не поддерживается."""

    def __init__(self, path: str, extension: str) -> None:
        self.path = path
        self.extension = extension
        supported = ", ".join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
        super().__init__(
            f"Формат «{extension}» не поддерживается для «{path}». "
            f"Загрузите документ в одном из форматов: {supported}."
        )
