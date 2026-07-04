"""RQ-задачи фоновой обработки документов."""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path

from app.ingestion.clarification import ClarificationContext, ClarificationRequiredError
from app.ingestion.document_pipeline import continue_ingest_after_clarification, ingest_document_full
from app.ingestion.job_store import JobStore

logger = logging.getLogger(__name__)


def _result_summary(result) -> dict:
    parse = result.parse
    extraction = result.extraction
    stats = result.ingest_stats

    summary = {
        "pages": len(parse.pages),
        "images": len(parse.images),
        "entities_count": extraction.entity_count,
        "relations_count": extraction.relation_count,
        "prepared_document_path": parse.prepared_document_path,
        "extraction_json_path": result.extraction_json_path,
        "skipped_reingest": result.skipped_reingest,
    }
    if stats:
        summary.update(
            {
                "chunks_saved": stats.chunks_saved,
                "entities_saved": stats.entities_saved,
                "relations_saved": stats.relations_saved,
                "group_id": stats.group_id,
                "original_storage_path": stats.original_storage_path,
                "graphiti_chunks_ingested": stats.graphiti_chunks_ingested,
                "graphiti_chunks_skipped": stats.graphiti_chunks_skipped,
                "graphiti_skipped": stats.graphiti_skipped,
            }
        )
    return summary


def process_ingestion_job(job_id: str) -> dict:
    store = JobStore()
    job = store.load(job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}")

    store.set_status(job_id, "processing")

    def on_progress(_step_id: str, message: str) -> None:
        store.append_progress(job_id, message)

    try:
        result = ingest_document_full(
            Path(job.file_path),
            document_category=job.document_category,
            analyze_images=job.analyze_images,
            on_progress=on_progress,
            force_reingest=job.force_reingest,
        )
        summary = _result_summary(result)
        store.mark_completed(job_id, **summary)
        logger.info("Job %s completed", job_id)
        return summary
    except ClarificationRequiredError as exc:
        logger.info("Job %s awaiting clarification", job_id)
        store.mark_awaiting_clarification(
            job_id,
            context=asdict(exc.context),
            partial_summary={
                "prepared_document_path": exc.context.prepared_document_path,
            },
        )
        return {
            "status": "awaiting_clarification",
            "questions": exc.context.questions,
        }
    except Exception as exc:
        logger.exception("Job %s failed: %s", job_id, exc)
        store.mark_failed(job_id, str(exc))
        raise


def process_clarification_job(
    job_id: str,
    answers: list[str],
    *,
    force_answer: bool = False,
) -> dict:
    store = JobStore()
    job = store.load(job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}")
    if not job.clarification_context:
        raise ValueError(f"Job {job_id} has no clarification context")

    context = ClarificationContext(**job.clarification_context)
    store.set_status(job_id, "processing")

    def on_progress(_step_id: str, message: str) -> None:
        store.append_progress(job_id, message)

    try:
        result = continue_ingest_after_clarification(
            context,
            answers=answers,
            force_answer=force_answer,
            on_progress=on_progress,
            force_reingest=job.force_reingest,
        )
        summary = _result_summary(result)
        store.mark_completed(job_id, **summary)
        logger.info("Job %s completed after clarification", job_id)
        return summary
    except ClarificationRequiredError as exc:
        store.mark_awaiting_clarification(
            job_id,
            context=asdict(exc.context),
            partial_summary={
                "prepared_document_path": exc.context.prepared_document_path,
            },
        )
        return {
            "status": "awaiting_clarification",
            "questions": exc.context.questions,
        }
    except Exception as exc:
        logger.exception("Job %s clarification failed: %s", job_id, exc)
        store.mark_failed(job_id, str(exc))
        raise
