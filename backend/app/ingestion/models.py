"""Модели данных пайплайна парсинга (документ, изображение)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DocumentImage:
    """Изображение (рисунок) из документа."""

    image_id: str
    page: int
    data: bytes
    mime: str
    width: int = 0
    height: int = 0


@dataclass
class ParseResult:
    """Результат полного парсинга: текст + описания изображений."""

    source_path: str
    doc_type: str
    pdf_path: str
    language_hint: str
    pages: list[tuple[int, str]]
    full_text: str
    images: list[DocumentImage] = field(default_factory=list)
    image_descriptions: dict[str, str] = field(default_factory=dict)

    def text_with_descriptions(self) -> str:
        """Текст документа: плейсхолдеры [IMG:id] заменены на описания VLM."""
        text = self.full_text
        for image_id, description in self.image_descriptions.items():
            token = f"[IMG:{image_id}]"
            replacement = f"[FIGURE {image_id}]: {description}"
            text = text.replace(token, replacement)
        return text
