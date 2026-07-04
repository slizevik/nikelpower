"""Обёртки Yandex API с учётом токенов и проверкой лимита."""

from __future__ import annotations

from openai import OpenAI

from app.llm.token_budget import (
    count_tokens,
    get_token_budget,
    usage_from_api_response,
)


def embeddings_create(
    client: OpenAI,
    *,
    model: str,
    input: str,
) -> object:
    budget = get_token_budget()
    estimate = count_tokens(input)

    budget.check_available(estimate)
    response = client.embeddings.create(
        model=model,
        input=input,
        encoding_format="float",
    )

    budget.record_text_as_tokens(input, "embeddings", response=response)

    return response


def chat_completions_create(
    client: OpenAI,
    *,
    model: str,
    messages: list[dict],
    **kwargs,
) -> object:
    budget = get_token_budget()
    prompt_text = "\n".join(
        str(m.get("content", "")) for m in messages if isinstance(m, dict)
    )
    estimate = count_tokens(prompt_text) + 256
    budget.check_available(estimate)

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        **kwargs,
    )

    usage = usage_from_api_response(response)
    if usage is not None:
        budget.record(usage, "chat")
    else:
        completion = ""
        if response.choices:
            completion = getattr(response.choices[0].message, "content", "") or ""
        budget.record(count_tokens(prompt_text) + count_tokens(completion), "chat")

    return response
