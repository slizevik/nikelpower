"""Вкладка «Загрузка документов» — Streamlit UI."""

from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path

import streamlit as st

from app.config import settings
from app.ingestion.clarification import ClarificationContext, ClarificationRequiredError
from app.ingestion.document_pipeline import continue_ingest_after_clarification, ingest_document_full
from app.ingestion.exceptions import UnsupportedFormatError
from app.ingestion.job_store import IngestionJob, JobStore
from app.ingestion.queue_client import (
    enqueue_clarification_continue,
    enqueue_ingestion_job,
    is_redis_available,
)
from app.ingestion.steps import IngestionStep
from app.ingestion.upload_store import save_uploaded_file
from app.ingestion.validation import validate_upload
from app.llm.token_budget import TokenBudgetExceeded, get_token_budget
from app.ui.progress_ring import render_circular_progress

DOCUMENT_CATEGORIES: list[tuple[str, str]] = [
    ("talk", "Доклады"),
    ("journal", "Журналы"),
    ("conference", "Материалы конференций"),
    ("review", "Обзоры"),
    ("article", "Статьи"),
    ("other", "Другое"),
]

PIPELINE_STEPS: list[IngestionStep] = [
    IngestionStep.VALIDATING,
    IngestionStep.CONVERTING_PDF,
    IngestionStep.EXTRACTING,
    IngestionStep.ANALYZING_IMAGES,
    IngestionStep.BUILDING_PREPARED,
    IngestionStep.EXTRACTING_ENTITIES,
    IngestionStep.CHUNKING,
    IngestionStep.EMBEDDING_AND_SAVING,
    IngestionStep.SAVING_ENTITIES,
    IngestionStep.GRAPHITI_ENRICHMENT,
]

SUPPORTED_LABELS = "PDF, DOC, DOCX, PPTX"
MIN_CUSTOM_CATEGORY_LEN = 3


def _category_label(category_id: str) -> str:
    for cid, label in DOCUMENT_CATEGORIES:
        if cid == category_id:
            return label
    return category_id


def _resolve_category(category_id: str, custom_name: str) -> tuple[str | None, str | None]:
    if category_id != "other":
        return category_id, None
    name = custom_name.strip()
    if len(name) < MIN_CUSTOM_CATEGORY_LEN:
        return None, f"Укажите название категории (минимум {MIN_CUSTOM_CATEGORY_LEN} символа)."
    return name, None


def _progress_fraction(current_label: str, completed: list[str]) -> float:
    labels = [s.label for s in PIPELINE_STEPS]
    if current_label in labels:
        return (labels.index(current_label) + 1) / len(labels)
    if completed:
        last = completed[-1]
        if last in labels:
            return (labels.index(last) + 1) / len(labels)
    return max(0.05, len(completed) / len(labels))


def _show_ingest_metrics(
    *,
    name: str,
    category: str,
    pages: int,
    images: int,
    entities_count: int,
    relations_count: int,
    chunks_saved: int | None = None,
    entities_saved: int | None = None,
    relations_saved: int | None = None,
    group_id: str | None = None,
    original_storage_path: str | None = None,
    skipped_reingest: bool = False,
    graphiti_chunks_ingested: int | None = None,
    graphiti_chunks_skipped: int | None = None,
    graphiti_skipped: bool | None = None,
) -> None:
    cat_display = (
        category
        if category not in {c[0] for c in DOCUMENT_CATEGORIES}
        else _category_label(category)
    )
    if skipped_reingest:
        st.info(
            f"Документ **{name}** уже был в базе (пропуск). group_id: `{group_id}`"
        )
    else:
        st.success(
            f"Документ **{name}** успешно загружен в базу данных "
            f"(категория: **{cat_display}**)."
        )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Страниц", pages)
    c2.metric("Изображений", images)
    c3.metric("Сущностей", entities_count)
    c4.metric("Связей", relations_count)

    if chunks_saved is not None:
        st.markdown("**Neo4j:**")
        m1, m2, m3 = st.columns(3)
        m1.metric("Чанков RAG", chunks_saved)
        m2.metric("Сущностей в БД", entities_saved or 0)
        m3.metric("Связей в БД", relations_saved or 0)
        if group_id:
            st.caption(f"group_id: `{group_id}`")
        if original_storage_path:
            st.caption(f"Исходный файл: `{original_storage_path}`")

    if graphiti_chunks_ingested is not None and not graphiti_skipped:
        st.markdown("**Graphiti:**")
        g1, g2 = st.columns(2)
        g1.metric("Эпизодов загружено", graphiti_chunks_ingested)
        g2.metric("Пропущено (идемп.)", graphiti_chunks_skipped or 0)
    elif graphiti_skipped and not skipped_reingest:
        st.caption(
            "Graphiti enrichment пропущен (нет graphiti-core в backend; работает в worker)."
        )


def _show_completed_job(job: IngestionJob) -> None:
    _show_ingest_metrics(
        name=job.original_name,
        category=job.document_category,
        pages=job.pages or 0,
        images=job.images or 0,
        entities_count=job.entities_count or 0,
        relations_count=job.relations_count or 0,
        chunks_saved=job.chunks_saved,
        entities_saved=job.entities_saved,
        relations_saved=job.relations_saved,
        group_id=job.group_id,
        original_storage_path=job.original_storage_path,
        skipped_reingest=bool(job.skipped_reingest),
        graphiti_chunks_ingested=job.graphiti_chunks_ingested,
        graphiti_chunks_skipped=job.graphiti_chunks_skipped,
        graphiti_skipped=job.graphiti_skipped,
    )


def _render_clarification_form(context_data: dict, *, job_id: str | None = None) -> None:
    context = ClarificationContext(**context_data)
    st.warning("Модель запросила уточнения перед загрузкой в Neo4j.")
    answers: list[str] = []
    with st.form("clarification_form", clear_on_submit=False):
        for i, question in enumerate(context.questions, 1):
            st.markdown(f"**{i}.** {question}")
            answers.append(st.text_area(f"Ответ {i}", key=f"clar_{job_id or 'sync'}_{i}"))
        c1, c2 = st.columns(2)
        force = c1.form_submit_button("Завершить без ответов")
        submit = c2.form_submit_button("Отправить и продолжить", type="primary")
    if force or submit:
        _submit_clarification(
            context,
            answers=[a.strip() for a in answers if a.strip()] if submit else [],
            force_answer=force,
            job_id=job_id,
        )


def _submit_clarification(
    context: ClarificationContext,
    *,
    answers: list[str],
    force_answer: bool,
    job_id: str | None,
) -> None:
    if job_id and is_redis_available():
        enqueue_clarification_continue(job_id, answers, force_answer=force_answer)
        st.session_state["ingestion_job_id"] = job_id
        st.session_state.pop("clarification_pending", None)
        st.rerun()
        return

    budget = get_token_budget()
    budget.begin_request()
    progress_log: list[str] = []
    progress_slot = st.empty()

    def on_progress(_step_id: str, message: str) -> None:
        progress_log.append(message)
        with progress_slot.container():
            render_circular_progress(_progress_fraction(message, progress_log), message)

    try:
        result = continue_ingest_after_clarification(
            context, answers=answers, force_answer=force_answer, on_progress=on_progress
        )
        st.session_state.pop("clarification_pending", None)
        parse, extraction, stats = result.parse, result.extraction, result.ingest_stats
        _show_ingest_metrics(
            name=Path(context.file_path).name,
            category=context.document_category,
            pages=len(parse.pages),
            images=len(parse.images),
            entities_count=extraction.entity_count,
            relations_count=extraction.relation_count,
            chunks_saved=stats.chunks_saved if stats else None,
            entities_saved=stats.entities_saved if stats else None,
            relations_saved=stats.relations_saved if stats else None,
            group_id=stats.group_id if stats else None,
            original_storage_path=stats.original_storage_path if stats else None,
            skipped_reingest=result.skipped_reingest,
            graphiti_chunks_ingested=stats.graphiti_chunks_ingested if stats else None,
            graphiti_chunks_skipped=stats.graphiti_chunks_skipped if stats else None,
            graphiti_skipped=stats.graphiti_skipped if stats else None,
        )
    except ClarificationRequiredError as exc:
        st.session_state["clarification_pending"] = asdict(exc.context)
        st.rerun()
    except Exception as exc:
        st.error(str(exc))
    finally:
        budget.finish_request()


def _poll_active_job(progress_slot) -> None:
    job_id = st.session_state.get("ingestion_job_id")
    if not job_id:
        return

    store = JobStore()
    job = store.load(job_id)
    if job is None:
        if store.exists(job_id):
            time.sleep(1)
            st.rerun()
            return
        retries = int(st.session_state.get("job_load_retries", 0)) + 1
        st.session_state["job_load_retries"] = retries
        if retries < 5:
            time.sleep(1)
            st.rerun()
            return
        st.session_state.pop("job_load_retries", None)
        st.warning(
            f"Не удалось прочитать статус задачи `{job_id}`. "
            "Обработка могла продолжиться в worker — подождите минуту и обновите страницу (F5). "
            "Если документ не появился в базе, загрузите файл снова с «Перезагрузить, если документ уже в базе»."
        )
        st.session_state.pop("ingestion_job_id", None)
        return

    st.session_state.pop("job_load_retries", None)

    if job.status == "awaiting_clarification" and job.clarification_context:
        _render_clarification_form(job.clarification_context, job_id=job_id)
        return

    if job.status in ("queued", "processing"):
        step = job.current_step or ("В очереди" if job.status == "queued" else "Обработка")
        with progress_slot.container():
            render_circular_progress(_progress_fraction(step, job.progress_log), step)
        time.sleep(2)
        st.rerun()
        return

    if job.status == "completed":
        with progress_slot.container():
            render_circular_progress(1.0, "Загрузка завершена")
        _show_completed_job(job)
        st.session_state.pop("ingestion_job_id", None)
        return

    if job.status == "failed":
        st.error(f"Ошибка обработки: {job.error}")
        if job.progress_log:
            st.markdown("**Выполнено до ошибки:**")
            for line in job.progress_log:
                st.markdown(f"- {line}")
        st.session_state.pop("ingestion_job_id", None)


def render_upload_tab() -> None:
    st.markdown("## Загрузка документов")
    st.caption(f"Форматы: {SUPPORTED_LABELS}")

    progress_slot = st.empty()

    pending = st.session_state.get("clarification_pending")
    if pending and not st.session_state.get("ingestion_job_id"):
        _render_clarification_form(pending)
        return

    _poll_active_job(progress_slot)

    uploaded = st.file_uploader("Файл документа", type=["pdf", "doc", "docx", "pptx"])

    category_id = st.selectbox(
        "Категория документа",
        options=[c[0] for c in DOCUMENT_CATEGORIES],
        format_func=_category_label,
    )

    custom_category = ""
    if category_id == "other":
        custom_category = st.text_input(
            "Название категории",
            placeholder="Введите название (мин. 3 символа)",
            max_chars=120,
        )
        if custom_category and len(custom_category.strip()) < MIN_CUSTOM_CATEGORY_LEN:
            st.caption(f":orange[Минимум {MIN_CUSTOM_CATEGORY_LEN} символа]")

    with st.expander("Дополнительные параметры"):
        analyze_images = st.checkbox(
            "Анализ изображений (Qwen-VL)",
            value=settings.analyze_document_images,
            help="Самый медленный шаг. Отключите для быстрой загрузки без описания рисунков.",
        )
        force_reingest = st.checkbox(
            "Перезагрузить, если документ уже в базе",
            value=settings.force_reingest,
        )
        redis_ok = is_redis_available()
        use_background = st.checkbox(
            "Обработка в фоне (worker)",
            value=redis_ok,
            disabled=not redis_ok,
        )

    if uploaded is None:
        if not st.session_state.get("ingestion_job_id"):
            st.info("Выберите файл и нажмите «Загрузить в базу данных».")
        return

    st.caption(f"{uploaded.name} · {uploaded.size / 1024:.1f} KB")

    if st.button("Загрузить в базу данных", type="primary", use_container_width=True):
        category, err = _resolve_category(category_id, custom_category)
        if err:
            st.error(err)
            return

        if use_background and is_redis_available():
            _enqueue_upload(
                uploaded, category, analyze_images, force_reingest, progress_slot
            )
        else:
            _run_sync_upload(
                uploaded, category, analyze_images, force_reingest, progress_slot
            )


def _enqueue_upload(
    uploaded,
    category: str,
    analyze_images: bool,
    force_reingest: bool,
    progress_slot,
) -> None:
    try:
        meta = save_uploaded_file(uploaded.getvalue(), uploaded.name, category)
        saved_path = Path(meta.saved_path)
        validation = validate_upload(saved_path)
        if not validation.ok:
            st.error(validation.message)
            return

        with progress_slot.container():
            render_circular_progress(0.05, "Постановка задачи в очередь…")

        job = enqueue_ingestion_job(
            file_path=str(saved_path),
            original_name=uploaded.name,
            document_category=category,
            analyze_images=analyze_images,
            force_reingest=force_reingest,
        )
        st.session_state["ingestion_job_id"] = job.job_id
        st.rerun()
    except Exception as exc:
        st.error(f"Не удалось поставить задачу в очередь: {exc}")


def _run_sync_upload(
    uploaded,
    category: str,
    analyze_images: bool,
    force_reingest: bool,
    progress_slot,
) -> None:
    budget = get_token_budget()
    budget.begin_request()
    progress_log: list[str] = []

    def stream_progress(_step_id: str, message: str) -> None:
        progress_log.append(message)
        with progress_slot.container():
            render_circular_progress(_progress_fraction(message, progress_log), message)

    try:
        with progress_slot.container():
            render_circular_progress(0.05, IngestionStep.VALIDATING.label)

        meta = save_uploaded_file(uploaded.getvalue(), uploaded.name, category)
        saved_path = Path(meta.saved_path)

        validation = validate_upload(saved_path)
        if not validation.ok:
            st.error(validation.message)
            return

        stream_progress(IngestionStep.VALIDATING.value, IngestionStep.VALIDATING.label)

        pipeline_result = ingest_document_full(
            saved_path,
            document_category=category,
            analyze_images=analyze_images,
            on_progress=stream_progress,
            force_reingest=force_reingest,
        )
        result = pipeline_result.parse
        extraction = pipeline_result.extraction
        ingest_stats = pipeline_result.ingest_stats

        with progress_slot.container():
            render_circular_progress(1.0, "Загрузка завершена")

        _show_ingest_metrics(
            name=uploaded.name,
            category=category,
            pages=len(result.pages),
            images=len(result.images),
            entities_count=extraction.entity_count,
            relations_count=extraction.relation_count,
            chunks_saved=ingest_stats.chunks_saved if ingest_stats else None,
            entities_saved=ingest_stats.entities_saved if ingest_stats else None,
            relations_saved=ingest_stats.relations_saved if ingest_stats else None,
            group_id=ingest_stats.group_id if ingest_stats else None,
            original_storage_path=ingest_stats.original_storage_path if ingest_stats else None,
            skipped_reingest=pipeline_result.skipped_reingest,
            graphiti_chunks_ingested=ingest_stats.graphiti_chunks_ingested if ingest_stats else None,
            graphiti_chunks_skipped=ingest_stats.graphiti_chunks_skipped if ingest_stats else None,
            graphiti_skipped=ingest_stats.graphiti_skipped if ingest_stats else None,
        )

    except ClarificationRequiredError as exc:
        st.session_state["clarification_pending"] = asdict(exc.context)
        st.rerun()
    except UnsupportedFormatError as exc:
        st.error(str(exc))
    except TokenBudgetExceeded as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"Ошибка при обработке документа: {exc}")
        if progress_log:
            st.markdown("**Выполнено до ошибки:**")
            for line in progress_log:
                st.markdown(f"- {line}")
    finally:
        budget.finish_request()
