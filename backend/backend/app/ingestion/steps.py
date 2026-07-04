"""Шаги пайплайна загрузки документа (отображение во Frontend)."""

from __future__ import annotations

from enum import Enum
from typing import Callable

ProgressCallback = Callable[[str, str], None]


class IngestionStep(str, Enum):
    VALIDATING = "validating"
    CONVERTING_PDF = "converting_pdf"
    EXTRACTING = "extracting"
    ANALYZING_IMAGES = "analyzing_images"
    BUILDING_PREPARED = "building_prepared"
    EXTRACTING_ENTITIES = "extracting_entities"
    CHUNKING = "chunking"
    EMBEDDING_AND_SAVING = "embedding_and_saving"
    SAVING_ENTITIES = "saving_entities"
    GRAPHITI_ENRICHMENT = "graphiti_enrichment"

    @property
    def label(self) -> str:
        labels = {
            IngestionStep.VALIDATING: 'Проверка формата документа',
            IngestionStep.CONVERTING_PDF: 'Конвертация в PDF',
            IngestionStep.EXTRACTING: 'Извлечение текста и изображений',
            IngestionStep.ANALYZING_IMAGES: 'Анализ изображений (Qwen-VL)',
            IngestionStep.BUILDING_PREPARED: 'Формирование подготовленного документа',
            IngestionStep.EXTRACTING_ENTITIES: 'Извлечение сущностей из документа',
            IngestionStep.CHUNKING: 'Разбиение текста для RAG',
            IngestionStep.EMBEDDING_AND_SAVING: 'Эмбеддинги и сохранение чанков в Neo4j',
            IngestionStep.SAVING_ENTITIES: 'Загрузка сущностей и связей в Neo4j',
            IngestionStep.GRAPHITI_ENRICHMENT: 'Обогащение графа знаний (Graphiti)',
        }
        return labels[self]


def report_progress(
    callback: ProgressCallback | None,
    step: IngestionStep,
    detail: str = "",
) -> None:
    if callback is None:
        return
    message = step.label if not detail else f'{step.label}: {detail}'
    callback(step.value, message)
