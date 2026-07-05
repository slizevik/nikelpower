"""Разбор JSON из ответов LLM (markdown, обрезки, trailing commas)."""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", stripped)
    if fence:
        return fence.group(1).strip()
    return stripped


def _repair_trailing_commas(text: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", text)


def _object_slice(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    return text[start : end + 1]


def parse_llm_json(raw: str) -> dict:
    """Парсит JSON из ответа LLM; бросает JSONDecodeError если не удалось."""
    text = _strip_markdown_fence(raw)
    candidates: list[str] = [text]
    sliced = _object_slice(text)
    if sliced and sliced not in candidates:
        candidates.append(sliced)
        candidates.append(_repair_trailing_commas(sliced))

    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as exc:
            last_error = exc

    try:
        from json_repair import repair_json

        for candidate in candidates:
            repaired = repair_json(candidate)
            parsed = json.loads(repaired)
            if isinstance(parsed, dict):
                logger.info("JSON восстановлен через json-repair")
                return parsed
    except ImportError:
        pass
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.debug("json-repair не помог: %s", exc)

    if last_error is not None:
        raise last_error
    raise json.JSONDecodeError("LLM response is not a JSON object", raw[:200], 0)
