"""Протокол уточнений при извлечении сущностей."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.ingestion.entity_extraction_prompt import ExtractionInteractionState
from app.models.extraction import EntityExtractionResult


@dataclass
class ClarificationContext:
    file_path: str
    document_category: str
    analyze_images: bool
    prepared_document_path: str
    source_path: str
    document_title: str
    language_hint: str | None
    questions: list[str]
    previous_questions: list[str] = field(default_factory=list)
    user_answers: list[str] = field(default_factory=list)

    @property
    def questions_asked_count(self) -> int:
        return len(self.previous_questions) + len(self.questions)

    def to_interaction(
        self,
        *,
        new_answers: list[str] | None = None,
        force_answer: bool = False,
    ) -> ExtractionInteractionState:
        answers = list(self.user_answers)
        if new_answers:
            answers.extend(new_answers)
        prev = list(self.previous_questions)
        prev.extend(self.questions)
        return ExtractionInteractionState(
            questions_asked_count=len(prev),
            previous_questions=prev,
            user_answers=answers,
            user_force_answer=force_answer,
        )


class ClarificationRequiredError(Exception):
    """Извлечение остановлено — модель запросила уточнения."""

    def __init__(self, context: ClarificationContext, extraction: EntityExtractionResult) -> None:
        self.context = context
        self.extraction = extraction
        super().__init__(
            "Требуются уточнения: " + "; ".join(context.questions[:3])
        )


def build_clarification_context(
    *,
    file_path: str,
    document_category: str,
    analyze_images: bool,
    prepared_document_path: str,
    source_path: str,
    document_title: str,
    language_hint: str | None,
    extraction: EntityExtractionResult,
    previous: ClarificationContext | None = None,
) -> ClarificationContext:
    prev_questions = list(previous.previous_questions) if previous else []
    prev_answers = list(previous.user_answers) if previous else []
    if previous:
        prev_questions.extend(previous.questions)

    return ClarificationContext(
        file_path=file_path,
        document_category=document_category,
        analyze_images=analyze_images,
        prepared_document_path=prepared_document_path,
        source_path=source_path,
        document_title=document_title,
        language_hint=language_hint,
        questions=list(extraction.clarification_questions),
        previous_questions=prev_questions,
        user_answers=prev_answers,
    )
