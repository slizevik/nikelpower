"""Хранение статуса фоновых задач загрузки документов."""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.config import settings

logger = logging.getLogger(__name__)

JobStatus = Literal["queued", "processing", "completed", "failed", "awaiting_clarification"]


@dataclass
class IngestionJob:
    job_id: str
    status: JobStatus
    file_path: str
    original_name: str
    document_category: str
    analyze_images: bool = True
    force_reingest: bool = False
    current_step: str = ""
    progress_log: list[str] = field(default_factory=list)
    error: str | None = None
    rq_job_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    pages: int | None = None
    images: int | None = None
    entities_count: int | None = None
    relations_count: int | None = None
    chunks_saved: int | None = None
    entities_saved: int | None = None
    relations_saved: int | None = None
    group_id: str | None = None
    original_storage_path: str | None = None
    prepared_document_path: str | None = None
    extraction_json_path: str | None = None
    clarification_context: dict | None = None
    skipped_reingest: bool | None = None
    graphiti_chunks_ingested: int | None = None
    graphiti_chunks_skipped: int | None = None
    graphiti_skipped: bool | None = None


class JobStore:
    def __init__(self, jobs_dir: Path | None = None) -> None:
        self.jobs_dir = jobs_dir or (settings.ingestion_state_dir / "jobs")
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def create(
        self,
        *,
        file_path: str,
        original_name: str,
        document_category: str,
        analyze_images: bool,
        force_reingest: bool = False,
    ) -> IngestionJob:
        job = IngestionJob(
            job_id=uuid.uuid4().hex[:12],
            status="queued",
            file_path=file_path,
            original_name=original_name,
            document_category=document_category,
            analyze_images=analyze_images,
            force_reingest=force_reingest,
        )
        self.save(job)
        return job

    def save(self, job: IngestionJob) -> None:
        job.updated_at = datetime.now(timezone.utc).isoformat()
        path = self._path(job.job_id)
        payload = json.dumps(asdict(job), ensure_ascii=False, indent=2)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, path)

    def exists(self, job_id: str) -> bool:
        return self._path(job_id).exists()

    def load(self, job_id: str) -> IngestionJob | None:
        path = self._path(job_id)
        if not path.exists():
            return None
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            logger.warning("Job file %s is empty", job_id)
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Job file %s is not valid JSON yet: %s", job_id, exc)
            return None
        return IngestionJob(**data)

    def set_status(self, job_id: str, status: JobStatus) -> None:
        job = self.load(job_id)
        if not job:
            return
        job.status = status
        self.save(job)

    def append_progress(self, job_id: str, message: str) -> None:
        job = self.load(job_id)
        if not job:
            return
        job.current_step = message
        if not job.progress_log or job.progress_log[-1] != message:
            job.progress_log.append(message)
        if job.status == "queued":
            job.status = "processing"
        self.save(job)

    def mark_completed(self, job_id: str, **result_fields) -> None:
        job = self.load(job_id)
        if not job:
            return
        job.status = "completed"
        for key, value in result_fields.items():
            if hasattr(job, key):
                setattr(job, key, value)
        self.save(job)

    def mark_failed(self, job_id: str, error: str) -> None:
        job = self.load(job_id)
        if not job:
            return
        job.status = "failed"
        job.error = error
        self.save(job)

    def mark_awaiting_clarification(
        self,
        job_id: str,
        *,
        context: dict,
        partial_summary: dict | None = None,
    ) -> None:
        job = self.load(job_id)
        if not job:
            return
        job.status = "awaiting_clarification"
        job.clarification_context = context
        if partial_summary:
            for key, value in partial_summary.items():
                if hasattr(job, key):
                    setattr(job, key, value)
        self.save(job)
