"""LLM-клиент Graphiti, адаптированный под Yandex AI (Qwen)."""

from __future__ import annotations

import json
import logging
import typing
from typing import Any

from pydantic import BaseModel, ValidationError

from graphiti_core.llm_client.config import ModelSize
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.prompts.models import Message

logger = logging.getLogger(__name__)

_STRUCTURED_HINTS: dict[str, str] = {
    "ExtractedEdges": (
        'Верните JSON с данными (не JSON Schema): {"edges": [{"source_entity_name": "...", '
        '"target_entity_name": "...", "relation_type": "USES_MATERIAL", "fact": "..."}]}. '
        'Если связей нет: {"edges": []}. Не возвращайте $defs, properties, type.'
    ),
    "ExtractedEntities": (
        'Верните JSON с данными: {"extracted_entities": [{"name": "...", "entity_type_id": 1}]}. '
        'Если сущностей нет: {"extracted_entities": []}.'
    ),
    "SummarizedEntities": (
        'Верните JSON: {"summaries": [{"name": "...", "summary": "..."}]}. '
        'Если обновлений нет: {"summaries": []}.'
    ),
    "EdgeDuplicate": (
        'Верните JSON: {"duplicate_facts": [], "contradicted_facts": []}.'
    ),
    "NodeResolutions": (
        'Верните JSON: {"entity_resolutions": [{"id": 0, "name": "...", "duplicate_candidate_id": -1}]}.'
    ),
    "BatchEdgeTimestamps": (
        'Верните JSON: {"timestamps": [{"valid_at": null, "invalid_at": null}]}.'
    ),
}

_EMPTY_PAYLOADS: dict[str, dict[str, Any]] = {
    "ExtractedEdges": {"edges": []},
    "ExtractedEntities": {"extracted_entities": []},
    "SummarizedEntities": {"summaries": []},
    "EdgeDuplicate": {"duplicate_facts": [], "contradicted_facts": []},
    "NodeResolutions": {"entity_resolutions": []},
    "BatchEdgeTimestamps": {"timestamps": []},
}


def _looks_like_json_schema(payload: dict[str, Any]) -> bool:
    if "$defs" in payload or "definitions" in payload:
        return True
    if payload.get("type") == "object" and "properties" in payload:
        return True
    title = payload.get("title")
    return isinstance(title, str) and title.endswith("Edges")


def _empty_payload(response_model: type[BaseModel]) -> dict[str, Any]:
    name = response_model.__name__
    if name in _EMPTY_PAYLOADS:
        return dict(_EMPTY_PAYLOADS[name])
    required_lists = [
        field_name
        for field_name, field in response_model.model_fields.items()
        if field.is_required() and typing.get_origin(field.annotation) is list
    ]
    if len(required_lists) == 1:
        return {required_lists[0]: []}
    return {}


def _unwrap_payload(payload: dict[str, Any], response_model: type[BaseModel]) -> dict[str, Any]:
    model_name = response_model.__name__
    for key in (model_name, "data", "result", "response"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            return nested
    return payload


def _coerce_structured_response(
    payload: dict[str, Any],
    response_model: type[BaseModel],
) -> dict[str, Any]:
    data = _unwrap_payload(payload, response_model)
    if _looks_like_json_schema(data):
        logger.warning(
            "Yandex LLM вернула JSON Schema вместо данных для %s — используем пустой результат",
            response_model.__name__,
        )
        return _empty_payload(response_model)
    try:
        response_model.model_validate(data)
        return data
    except ValidationError as exc:
        logger.warning(
            "Невалидный structured-ответ для %s (%s) — используем пустой результат",
            response_model.__name__,
            exc.errors()[0].get("type") if exc.errors() else exc,
        )
        return _empty_payload(response_model)


class YandexGraphitiLLMClient(OpenAIGenericClient):
    """json_object + подсказки и нормализация ответа для Qwen через Yandex."""

    def _append_structured_hint(
        self,
        messages: list[Message],
        response_model: type[BaseModel],
    ) -> None:
        hint = _STRUCTURED_HINTS.get(response_model.__name__)
        if not hint:
            required = [
                name
                for name, field in response_model.model_fields.items()
                if field.is_required()
            ]
            hint = (
                "Верните JSON с полями данных (не JSON Schema): "
                f"{json.dumps({k: '...' for k in required}, ensure_ascii=False)}. "
                "Не возвращайте $defs, properties, type."
            )
        messages[-1].content += f"\n\n{hint}"

    async def generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int | None = None,
        model_size: ModelSize = ModelSize.medium,
        group_id: str | None = None,
        prompt_name: str | None = None,
        *,
        attribute_extraction: bool = False,
    ) -> dict[str, typing.Any]:
        self._apply_attribute_extraction_preamble(messages, attribute_extraction)
        if max_tokens is None:
            max_tokens = self.max_tokens

        if response_model is not None and self.structured_output_mode == "json_object":
            self._append_structured_hint(messages, response_model)

        from graphiti_core.llm_client.client import get_extraction_language_instruction

        messages[0].content += get_extraction_language_instruction(group_id)

        with self.tracer.start_span("llm.generate") as span:
            attributes = {
                "llm.provider": "yandex",
                "model.size": model_size.value,
                "max_tokens": max_tokens,
            }
            if prompt_name:
                attributes["prompt.name"] = prompt_name
            span.add_attributes(attributes)

            try:
                result = await self._generate_response_with_retry(
                    messages,
                    response_model,
                    max_tokens=max_tokens,
                    model_size=model_size,
                )
                if response_model is not None:
                    coerced = _coerce_structured_response(result, response_model)
                    if coerced is not result and _looks_like_json_schema(result):
                        retry_messages = [
                            Message(role=m.role, content=m.content) for m in messages
                        ]
                        retry_messages[-1].content += (
                            "\n\nВАЖНО: верните только JSON-данные с заполненными полями, "
                            "а не описание схемы JSON Schema."
                        )
                        result = await self._generate_response_with_retry(
                            retry_messages,
                            response_model,
                            max_tokens=max_tokens,
                            model_size=model_size,
                        )
                        coerced = _coerce_structured_response(result, response_model)
                    return coerced
                return result
            except Exception as exc:
                span.set_status("error", str(exc))
                span.record_exception(exc)
                raise
