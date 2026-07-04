"""Полный пайплайн: подготовка → извлечение сущностей → Neo4j (RAG) → Graphiti."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.ingestion.checkpoint import CheckpointStore, compute_file_content_hash, document_group_id
from app.ingestion.clarification import (
    ClarificationContext,
    ClarificationRequiredError,
    build_clarification_context,
)
from app.ingestion.entity_extraction_prompt import ExtractionInteractionState
from app.ingestion.entity_extractor import (
    extract_entities_from_prepared_text,
    extract_entities_from_prepared_file,
    save_extraction_result,
)
from app.ingestion.models import ParseResult
from app.ingestion.neo4j_ingest import Neo4jIngestionPipeline
from app.ingestion.orchestrator import parse_document_full
from app.ingestion.chunk_store import IngestStats
from app.ingestion.steps import IngestionStep, ProgressCallback, report_progress
from app.models.extraction import EntityExtractionResult

logger = logging.getLogger(__name__)


@dataclass
class DocumentIngestResult:
    parse: ParseResult
    extraction: EntityExtractionResult
    ingest_stats: IngestStats | None = None
    extraction_json_path: str | None = None
    skipped_reingest: bool = False


def _check_clarification(
    *,
    file_path: Path,
    document_category: str,
    analyze_images: bool,
    parse_result: ParseResult,
    extraction: EntityExtractionResult,
    previous: ClarificationContext | None = None,
) -> None:
    if not extraction.needs_clarification:
        return

    rounds = (
        (previous.questions_asked_count if previous else 0) + len(extraction.clarification_questions)
    )
    if rounds >= settings.max_clarification_rounds:
        logger.warning("Clarification limit reached (%s), continuing without answers", rounds)
        return

    context = build_clarification_context(
        file_path=str(file_path),
        document_category=document_category,
        analyze_images=analyze_images,
        prepared_document_path=parse_result.prepared_document_path or "",
        source_path=parse_result.source_path,
        document_title=Path(parse_result.source_path).name,
        language_hint=parse_result.language_hint,
        extraction=extraction,
        previous=previous,
    )

    content_hash = compute_file_content_hash(file_path)
    group_id = document_group_id(content_hash)
    CheckpointStore().mark_awaiting_clarification(group_id, context.questions)

    raise ClarificationRequiredError(context, extraction)


def prepare_document_with_entities(
    path: Path,
    *,
    document_category: str,
    analyze_images: bool | None = None,
    on_progress: ProgressCallback | None = None,
    interaction: ExtractionInteractionState | None = None,
    previous_clarification: ClarificationContext | None = None,
    skip_parse: bool = False,
    prepared_path: Path | None = None,
    parse_result: ParseResult | None = None,
) -> DocumentIngestResult:
    if skip_parse and prepared_path is not None:
        if parse_result is None:
            raise ValueError("parse_result required when skip_parse=True")
        report_progress(on_progress, IngestionStep.EXTRACTING_ENTITIES)
        extraction = extract_entities_from_prepared_file(
            prepared_path,
            source_path=parse_result.source_path,
            document_category=document_category,
            document_title=Path(parse_result.source_path).name,
            language_hint=parse_result.language_hint,
            interaction=interaction,
        )
    else:
        parse_result = parse_document_full(
            path,
            analyze_images=analyze_images,
            on_progress=on_progress,
        )

        report_progress(on_progress, IngestionStep.EXTRACTING_ENTITIES)
        prepared_text = parse_result.text_with_descriptions()

        extraction = extract_entities_from_prepared_text(
            prepared_text,
            source_path=parse_result.source_path,
            document_category=document_category,
            document_title=Path(parse_result.source_path).name,
            language_hint=parse_result.language_hint,
            interaction=interaction,
        )

    _check_clarification(
        file_path=path,
        document_category=document_category,
        analyze_images=analyze_images if analyze_images is not None else settings.analyze_document_images,
        parse_result=parse_result,
        extraction=extraction,
        previous=previous_clarification,
    )

    extraction_path: str | None = None
    if parse_result.prepared_document_path:
        saved = save_extraction_result(extraction, parse_result.prepared_document_path)
        extraction_path = str(saved)

    return DocumentIngestResult(
        parse=parse_result,
        extraction=extraction,
        extraction_json_path=extraction_path,
    )


def ingest_document_full(
    path: Path,
    *,
    document_category: str,
    analyze_images: bool | None = None,
    on_progress: ProgressCallback | None = None,
    interaction: ExtractionInteractionState | None = None,
    previous_clarification: ClarificationContext | None = None,
    force_reingest: bool | None = None,
    run_graphiti: bool | None = None,
) -> DocumentIngestResult:
    """Этапы 1–6: парсинг, VLM, сущности, RAG + Neo4j, Graphiti enrichment."""
    prepare = prepare_document_with_entities(
        path,
        document_category=document_category,
        analyze_images=analyze_images,
        on_progress=on_progress,
        interaction=interaction,
        previous_clarification=previous_clarification,
    )

    report_progress(on_progress, IngestionStep.CHUNKING)
    report_progress(on_progress, IngestionStep.EMBEDDING_AND_SAVING)

    pipeline = Neo4jIngestionPipeline()
    try:
        stats = pipeline.ingest_to_neo4j(
            prepare.parse,
            prepare.extraction,
            document_category=document_category,
            source_file=path,
            force_reingest=force_reingest,
            on_progress=on_progress,
            run_graphiti=run_graphiti,
        )
    finally:
        pipeline.close()

    report_progress(on_progress, IngestionStep.SAVING_ENTITIES)

    return DocumentIngestResult(
        parse=prepare.parse,
        extraction=prepare.extraction,
        ingest_stats=stats,
        extraction_json_path=prepare.extraction_json_path,
        skipped_reingest=stats.skipped_reingest,
    )


def continue_ingest_after_clarification(
    context: ClarificationContext,
    *,
    answers: list[str] | None = None,
    force_answer: bool = False,
    on_progress: ProgressCallback | None = None,
    force_reingest: bool | None = None,
    run_graphiti: bool | None = None,
    parse_result: ParseResult | None = None,
) -> DocumentIngestResult:
    """Повторное извлечение с ответами пользователя и завершение загрузки."""
    from app.ingestion.prepared_document import load_parse_snapshot

    path = Path(context.file_path)
    prepared_path = Path(context.prepared_document_path)

    if not prepared_path.exists():
        raise FileNotFoundError(f"Подготовленный документ не найден: {prepared_path}")

    if parse_result is None:
        parse_result = load_parse_snapshot(context.source_path)

    interaction = context.to_interaction(new_answers=answers, force_answer=force_answer)

    prepare = prepare_document_with_entities(
        path,
        document_category=context.document_category,
        analyze_images=context.analyze_images,
        on_progress=on_progress,
        interaction=interaction,
        previous_clarification=context,
        skip_parse=True,
        prepared_path=prepared_path,
        parse_result=parse_result,
    )

    report_progress(on_progress, IngestionStep.CHUNKING)
    report_progress(on_progress, IngestionStep.EMBEDDING_AND_SAVING)

    pipeline = Neo4jIngestionPipeline()
    try:
        stats = pipeline.ingest_to_neo4j(
            prepare.parse,
            prepare.extraction,
            document_category=context.document_category,
            source_file=path,
            force_reingest=force_reingest,
            on_progress=on_progress,
            run_graphiti=run_graphiti,
        )
    finally:
        pipeline.close()

    report_progress(on_progress, IngestionStep.SAVING_ENTITIES)

    return DocumentIngestResult(
        parse=prepare.parse,
        extraction=prepare.extraction,
        ingest_stats=stats,
        extraction_json_path=prepare.extraction_json_path,
        skipped_reingest=stats.skipped_reingest,
    )
