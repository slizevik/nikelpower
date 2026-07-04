"""Extract text from PDF, DOCX, and PPTX + facade полного пайплайна."""

from __future__ import annotations

from pathlib import Path

from app.ingestion.exceptions import SUPPORTED_DOCUMENT_EXTENSIONS, UnsupportedFormatError
from app.ingestion.language import detect_language_hint
from app.ingestion.parser_types import ParsedDocument

__all__ = [
    "ParsedDocument",
    "SUPPORTED_EXTENSIONS",
    "detect_language_hint",
    "parse_document",
    "parse_document_legacy",
    "iter_documents",
    "UnsupportedFormatError",
]

SUPPORTED_EXTENSIONS = SUPPORTED_DOCUMENT_EXTENSIONS


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


def parse_document(path: Path) -> ParsedDocument:
    from app.ingestion.orchestrator import parse_document_full, to_legacy_parsed_document

    return to_legacy_parsed_document(parse_document_full(path))


def parse_document_legacy(path: Path) -> ParsedDocument:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path)
    raise UnsupportedFormatError(str(path), suffix)


def iter_documents(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
