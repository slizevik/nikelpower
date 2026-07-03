"""Extract text from PDF, DOCX, and PPTX documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ParsedDocument:
    source_path: str
    doc_type: str
    language_hint: str
    pages: list[tuple[int, str]]  # (page_num, text)
    full_text: str


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx"}


def detect_language_hint(text: str) -> str:
    cyrillic = len(re.findall(r"[а-яА-ЯёЁ]", text))
    latin = len(re.findall(r"[a-zA-Z]", text))
    if cyrillic > latin * 1.5:
        return "ru"
    if latin > cyrillic * 1.5:
        return "en"
    return "mixed"


def parse_pdf(path: Path) -> ParsedDocument:
    import fitz

    pages: list[tuple[int, str]] = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if text:
                pages.append((i, text))
    full_text = "\n\n".join(t for _, t in pages)
    return ParsedDocument(
        source_path=str(path),
        doc_type="pdf",
        language_hint=detect_language_hint(full_text),
        pages=pages,
        full_text=full_text,
    )


def parse_docx(path: Path) -> ParsedDocument:
    from docx import Document

    doc = Document(path)
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    full_text = "\n\n".join(paragraphs)
    return ParsedDocument(
        source_path=str(path),
        doc_type="docx",
        language_hint=detect_language_hint(full_text),
        pages=[(1, full_text)] if full_text else [],
        full_text=full_text,
    )


def parse_pptx(path: Path) -> ParsedDocument:
    from pptx import Presentation

    prs = Presentation(path)
    pages: list[tuple[int, str]] = []
    for i, slide in enumerate(prs.slides, start=1):
        parts: list[str] = []
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                parts.append(shape.text.strip())
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                parts.append(f"[notes] {notes}")
        if parts:
            pages.append((i, "\n".join(parts)))
    full_text = "\n\n".join(t for _, t in pages)
    return ParsedDocument(
        source_path=str(path),
        doc_type="pptx",
        language_hint=detect_language_hint(full_text),
        pages=pages,
        full_text=full_text,
    )


def parse_document(path: Path) -> ParsedDocument:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path)
    if suffix == ".docx":
        return parse_docx(path)
    if suffix == ".pptx":
        return parse_pptx(path)
    raise ValueError(f"Unsupported format: {suffix}")


def iter_documents(root: Path) -> list[Path]:
    if not root.exists():
        return []
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(path)
    return files
