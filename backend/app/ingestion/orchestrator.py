"""Оркестратор парсинга: LibreOffice → PDF → текст + VLM для изображений."""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import settings
from app.ingestion.converter import ensure_pdf
from app.ingestion.exceptions import SUPPORTED_DOCUMENT_EXTENSIONS, UnsupportedFormatError
from app.ingestion.figures_store import save_document_images
from app.ingestion.models import ParseResult
from app.ingestion.pdf_extract import extract_pdf_content
from app.ingestion.prepared_document import save_prepared_document, save_parse_snapshot, save_raw_text
from app.ingestion.parser_types import ParsedDocument
from app.ingestion.steps import IngestionStep, ProgressCallback, report_progress
from app.ingestion.validation import require_supported
from app.ingestion.vision_client import analyze_images_sequential

logger = logging.getLogger(__name__)


def validate_document_path(path: Path) -> None:
    ext = path.suffix.lower()
    if ext not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise UnsupportedFormatError(str(path), ext)


def parse_document_full(
    path: Path,
    *,
    analyze_images: bool | None = None,
    on_progress: ProgressCallback | None = None,
) -> ParseResult:
    """
    Шаги 2–3 алгоритма загрузки:
    DOCX/PPTX→PDF (LibreOffice) → извлечение текста/изображений → Qwen-VL → подготовленный документ.
    """
    path = path.resolve()
    report_progress(on_progress, IngestionStep.VALIDATING, path.name)
    require_supported(path)

    do_vlm = settings.analyze_document_images if analyze_images is None else analyze_images
    original_type = path.suffix.lower().lstrip(".")

    if path.suffix.lower() != ".pdf":
        report_progress(on_progress, IngestionStep.CONVERTING_PDF, path.name)
    pdf_path = ensure_pdf(path)

    report_progress(on_progress, IngestionStep.EXTRACTING)
    pages, images, language_hint = extract_pdf_content(pdf_path, str(path))
    full_text = "\n\n".join(t for _, t in pages)

    descriptions: dict[str, str] = {}
    if do_vlm and images:
        report_progress(
            on_progress,
            IngestionStep.ANALYZING_IMAGES,
            f"{len(images)} изображений",
        )

        def _on_image(current: int, total: int, image_id: str) -> None:
            report_progress(
                on_progress,
                IngestionStep.ANALYZING_IMAGES,
                f"{current}/{total} ({image_id})",
            )

        descriptions = analyze_images_sequential(images, on_image=_on_image)

    result = ParseResult(
        source_path=str(path),
        doc_type=original_type,
        pdf_path=str(pdf_path),
        language_hint=language_hint,
        pages=pages,
        full_text=full_text,
        images=images,
        image_descriptions=descriptions,
    )

    report_progress(on_progress, IngestionStep.BUILDING_PREPARED)
    save_raw_text(result)
    prepared_path = save_prepared_document(result)
    result.prepared_document_path = str(prepared_path)
    save_parse_snapshot(result)

    if images:
        save_document_images(result)

    logger.info(
        "Parse complete: %s pages, %s images, prepared=%s",
        len(pages),
        len(images),
        prepared_path,
    )
    return result


def to_legacy_parsed_document(result: ParseResult) -> ParsedDocument:
    pages = _enrich_pages(result.pages, result.image_descriptions)
    return ParsedDocument(
        source_path=result.source_path,
        doc_type=result.doc_type,
        language_hint=result.language_hint,
        pages=pages,
        full_text=result.text_with_descriptions(),
    )


def _enrich_pages(
    pages: list[tuple[int, str]],
    descriptions: dict[str, str],
) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for page_num, text in pages:
        enriched = text
        for image_id, desc in descriptions.items():
            enriched = enriched.replace(f"[IMG:{image_id}]", f"[FIGURE {image_id}]: {desc}")
        out.append((page_num, enriched))
    return out
