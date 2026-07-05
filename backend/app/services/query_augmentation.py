"""Дополнение пользовательского запроса фильтрами Frontend."""

from __future__ import annotations

from app.models.chat import ChatSearchFilters

_COUNTRY_LABELS = {
    "all": "Географический контекст: отечественные и зарубежные источники.",
    "russia": "Географический контекст: отечественная практика, Россия, российские исследования и предприятия.",
    "foreign": "Географический контекст: зарубежная практика, международные публикации и технологии.",
}

_CATEGORY_LABELS = {
    "talk": "доклады",
    "journal": "журналы",
    "conference": "материалы конференций",
    "review": "обзоры",
    "article": "статьи",
    "other": "другое",
}


def augment_query(user_query: str, filters: ChatSearchFilters) -> str:
    parts = [user_query.strip()]

    country_hint = _COUNTRY_LABELS.get(filters.country, "")
    if country_hint and filters.country in ("russia", "foreign"):
        parts.append(country_hint)

    if filters.document_category and filters.document_category != "all":
        label = _CATEGORY_LABELS.get(filters.document_category, filters.document_category)
        parts.append(f"Тип документов: {label}.")

    if filters.material and filters.material.strip():
        parts.append(f"Материал / вещество: {filters.material.strip()}.")

    if filters.process_type and filters.process_type.strip():
        parts.append(f"Технологический процесс: {filters.process_type.strip()}.")

    if filters.year_from or filters.year_to:
        y_from = filters.year_from or "…"
        y_to = filters.year_to or "…"
        parts.append(f"Год публикации / эксперимента: {y_from}–{y_to}.")

    return " ".join(parts)
