"""Клиент очереди Redis/RQ для фоновой загрузки документов."""

from __future__ import annotations

import logging

from redis import Redis
from rq import Queue

from app.config import settings
from app.ingestion.job_store import IngestionJob, JobStore
from app.ingestion.tasks import process_clarification_job, process_ingestion_job

logger = logging.getLogger(__name__)

QUEUE_NAME = "ingestion"
JOB_TIMEOUT_SEC = 7200


def get_redis_connection() -> Redis:
    return Redis.from_url(settings.redis_url)


def is_redis_available() -> bool:
    try:
        conn = get_redis_connection()
        conn.ping()
        return True
    except Exception as exc:
        logger.debug("Redis unavailable: %s", exc)
        return False


def get_queue() -> Queue:
    conn = get_redis_connection()
    return Queue(QUEUE_NAME, connection=conn)


def enqueue_ingestion_job(
    *,
    file_path: str,
    original_name: str,
    document_category: str,
    analyze_images: bool,
    force_reingest: bool = False,
) -> IngestionJob:
    store = JobStore()
    job = store.create(
        file_path=file_path,
        original_name=original_name,
        document_category=document_category,
        analyze_images=analyze_images,
        force_reingest=force_reingest,
    )

    queue = get_queue()
    rq_job = queue.enqueue(
        process_ingestion_job,
        job.job_id,
        job_timeout=JOB_TIMEOUT_SEC,
        result_ttl=86400,
        failure_ttl=86400,
    )
    job.rq_job_id = rq_job.id
    store.save(job)
    logger.info("Enqueued ingestion job %s (rq=%s)", job.job_id, rq_job.id)
    return job


def enqueue_clarification_continue(
    job_id: str,
    answers: list[str],
    *,
    force_answer: bool = False,
) -> str:
    queue = get_queue()
    rq_job = queue.enqueue(
        process_clarification_job,
        job_id,
        answers,
        force_answer=force_answer,
        job_timeout=JOB_TIMEOUT_SEC,
        result_ttl=86400,
        failure_ttl=86400,
    )
    logger.info("Enqueued clarification continue for job %s (rq=%s)", job_id, rq_job.id)
    return rq_job.id
