"""Plain-text LLM chat completions for the Telegram agent.

Unlike claude.py (which expects structured JSON), this module returns
free-form text answers for conversational Q&A.
"""

from __future__ import annotations

import httpx

from src.config import Settings
from src.llm.models import anthropic_model_candidates, openrouter_model_candidates


def _format_http_error(provider: str, exc: httpx.HTTPStatusError) -> str:
    detail = exc.response.text.strip().replace("\n", " ")
    if len(detail) > 240:
        detail = detail[:240] + "…"
    return f"{provider}: HTTP {exc.response.status_code}" + (f" ({detail})" if detail else "")


def chat_completion(
    settings: Settings,
    system_prompt: str,
    messages: list[dict[str, str]],
) -> str:
    errors: list[str] = []
    for provider in settings.llm_providers:
        try:
            if provider == "anthropic":
                return _chat_anthropic(settings, system_prompt, messages)
            if provider == "openrouter":
                return _chat_openrouter(settings, system_prompt, messages)
            if provider == "openai":
                return _chat_openai(settings, system_prompt, messages)
        except httpx.HTTPStatusError as exc:
            errors.append(_format_http_error(provider, exc))
        except Exception as exc:
            errors.append(f"{provider}: {exc}")

    raise RuntimeError("All LLM providers failed: " + "; ".join(errors))


def _chat_anthropic(
    settings: Settings,
    system_prompt: str,
    messages: list[dict[str, str]],
) -> str:
    last_error: Exception | None = None
    for model in anthropic_model_candidates(settings.claude_model):
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": settings.llm_max_tokens,
                "system": system_prompt,
                "messages": messages,
            },
            timeout=180.0,
        )
        if response.status_code == 404:
            last_error = httpx.HTTPStatusError(
                f"Model not found: {model}",
                request=response.request,
                response=response,
            )
            continue
        response.raise_for_status()
        return response.json()["content"][0]["text"]

    if last_error is not None:
        raise last_error
    raise RuntimeError("No Anthropic models available to try")


def _chat_openrouter(
    settings: Settings,
    system_prompt: str,
    messages: list[dict[str, str]],
) -> str:
    last_error: httpx.HTTPStatusError | None = None
    payload_messages = [{"role": "system", "content": system_prompt}, *messages]

    for model in openrouter_model_candidates(settings.claude_model):
        response = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/TheMitchyBoy/Claude-LLM-Local-News-Analysis-",
                "X-Title": "Meeting Video Ideas Agent",
            },
            json={
                "model": model,
                "messages": payload_messages,
                "max_tokens": settings.llm_max_tokens,
            },
            timeout=180.0,
        )
        if response.status_code in {404, 402}:
            last_error = httpx.HTTPStatusError(
                f"Model unavailable: {model}",
                request=response.request,
                response=response,
            )
            continue
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    if last_error is not None:
        raise last_error
    raise RuntimeError("No OpenRouter models available to try")


def _chat_openai(
    settings: Settings,
    system_prompt: str,
    messages: list[dict[str, str]],
) -> str:
    payload_messages = [{"role": "system", "content": system_prompt}, *messages]
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.openai_fallback_model,
            "messages": payload_messages,
            "max_tokens": settings.llm_max_tokens,
        },
        timeout=180.0,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]
