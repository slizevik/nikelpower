"""Qwen-VL (Yandex OpenAI-compatible): описание изображений документа."""

from __future__ import annotations

import base64
import json
import logging
import re

from app.config import settings
from app.ingestion.models import DocumentImage
from app.ingestion.vision_prompt import VISION_SYSTEM_PROMPT, VISION_USER_PROMPT
from app.llm.tracked_api import chat_completions_create
from app.llm.yandex_client import get_yandex_client

logger = logging.getLogger(__name__)


def _vision_model() -> str:
    if settings.yandex_vision_model:
        return settings.yandex_vision_model
    if settings.yandex_cloud_model:
        return settings.yandex_cloud_model
    raise RuntimeError("YANDEX_VISION_MODEL или YANDEX_CLOUD_MODEL не задан")


def _parse_json_response(raw: str) -> dict:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def _description_from_json(payload: dict) -> str:
    if not payload.get("useful_for_analysis", True):
        return payload.get("summary") or "изображение бесполезно для анализа"
    parts = [payload.get("summary", "")]
    img_type = payload.get("image_type")
    if img_type:
        parts.insert(0, f"Тип: {img_type}.")
    values = payload.get("key_values") or []
    if values:
        parts.append("Значения: " + "; ".join(str(v) for v in values))
    analysis = payload.get("materials_analysis")
    if analysis:
        parts.append(str(analysis))
    return " ".join(p for p in parts if p).strip()


def analyze_image(image: DocumentImage) -> str:
    """Последовательный вызов VLM для одного изображения. Возвращает текст описания."""
    b64 = base64.standard_b64encode(image.data).decode("ascii")
    mime = image.mime if image.mime.startswith("image/") else "image/png"
    data_url = f"data:{mime};base64,{b64}"

    client = get_yandex_client()
    response = chat_completions_create(
        client,
        model=_vision_model(),
        messages=[
            {"role": "system", "content": VISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_USER_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        max_tokens=1024,
        temperature=0.2,
    )
    raw = response.choices[0].message.content or ""
    try:
        payload = _parse_json_response(raw)
        return _description_from_json(payload)
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning("VLM вернул не-JSON для %s, используем сырой текст", image.image_id)
        return raw.strip() or "не удалось описать изображение"


def analyze_images_sequential(images: list[DocumentImage]) -> dict[str, str]:
    """Анализ всех изображений по одному (ключ → описание)."""
    descriptions: dict[str, str] = {}
    for i, image in enumerate(images, 1):
        logger.info("VLM %s/%s: %s (стр. %s)", i, len(images), image.image_id, image.page)
        try:
            descriptions[image.image_id] = analyze_image(image)
        except Exception as exc:
            logger.error("VLM ошибка %s: %s", image.image_id, exc)
            descriptions[image.image_id] = f"ошибка анализа изображения: {exc}"
    return descriptions
