"""Claude structured analysis: transcripts → JSON video ideas.

Sends meeting transcripts to Claude with a JSON schema prompt and
returns parsed ideas. Handles model name normalization, provider
fallback, truncated responses, and JSON repair on parse failure.
"""

from __future__ import annotations

import httpx

from src.config import Settings
from src.llm.json_parse import LLMJSONError, parse_llm_json
from src.llm.models import anthropic_model_candidates, openrouter_model_candidates
from src.services.prompt_settings import build_guidance_prompt

BASE_SYSTEM_PROMPT = """You are a local news video producer and investigative journalist.
Analyze government meeting transcripts and propose compelling YouTube video topics.

For each meeting, identify the most newsworthy stories a local audience would care about.
Prioritize: budget impacts, controversial votes, public opposition, safety, housing,
education, infrastructure, and accountability.

Return ONLY valid JSON (no markdown fences) with this structure:
{
  "summary": "2-3 sentence overview of all meetings analyzed",
  "ideas": [
    {
      "title": "Catchy video title",
      "meeting_source": "Original meeting title",
      "hook": "One-sentence viewer hook",
      "angle": "Journalistic angle and why it matters locally",
      "key_points": ["point 1", "point 2", "point 3"],
      "research_queries": ["web search query 1", "web search query 2"],
      "urgency": "high|medium|low",
      "estimated_length": "short (3-5 min)|medium (8-12 min)|long (15+ min)"
    }
  ]
}

Rules:
- Produce 2-3 ideas per meeting (max 3).
- Keep every string under 180 characters.
- Escape double quotes inside strings.
- Do not include trailing commas.
- Return complete, valid JSON only."""

COMPACT_RETRY_PROMPT = """Your previous answer was incomplete or invalid JSON.
Return ONLY compact valid JSON with at most 2 ideas per meeting.
Keep every string under 120 characters. No markdown. No commentary."""


def get_system_prompt(guidance: dict | None = None) -> str:
    extra = build_guidance_prompt(guidance)
    return f"{BASE_SYSTEM_PROMPT}\n\nProducer preferences:\n{extra}"


def _format_http_error(provider: str, exc: httpx.HTTPStatusError) -> str:
    detail = exc.response.text.strip().replace("\n", " ")
    if len(detail) > 240:
        detail = detail[:240] + "…"
    return f"{provider}: HTTP {exc.response.status_code}" + (f" ({detail})" if detail else "")


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[... transcript truncated ...]"


def _build_user_content(transcripts: list[dict], max_chars: int) -> str:
    content = "Analyze these meeting transcripts and suggest video topics:\n\n"
    for item in transcripts:
        content += f"---\nMEETING: {item['title']}\n"
        if item.get("meeting_type"):
            content += f"TYPE: {item['meeting_type']}\n"
        if item.get("published_at"):
            content += f"DATE: {item['published_at']}\n"
        content += f"TRANSCRIPT:\n{_truncate_text(item['text'], max_chars)}\n\n"
    return content


def analyze_transcripts(
    settings: Settings,
    transcripts: list[dict],
    guidance: dict | None = None,
) -> dict:
    user_content = _build_user_content(transcripts, settings.max_transcript_chars)
    system_prompt = get_system_prompt(guidance)
    errors: list[str] = []

    for provider in settings.llm_providers:
        try:
            if provider == "anthropic":
                return _call_anthropic(settings, user_content, system_prompt)
            if provider == "openrouter":
                return _call_openrouter(settings, user_content, system_prompt)
            if provider == "openai":
                return _call_openai(settings, user_content, system_prompt)
        except httpx.HTTPStatusError as exc:
            errors.append(_format_http_error(provider, exc))
        except (LLMJSONError, RuntimeError) as exc:
            errors.append(f"{provider}: {exc}")
        except Exception as exc:
            errors.append(f"{provider}: {exc}")

    raise RuntimeError("All LLM providers failed: " + "; ".join(errors))


def _parse_llm_content(content: str, *, provider: str, stop_reason: str | None = None) -> dict:
    try:
        return parse_llm_json(content)
    except LLMJSONError as exc:
        if stop_reason == "max_tokens":
            raise LLMJSONError(f"{provider}: response truncated at max_tokens") from exc
        raise LLMJSONError(f"{provider}: {exc}") from exc


def _retry_messages(user_content: str, broken_response: str) -> list[dict]:
    return [
        {"role": "user", "content": user_content},
        {
            "role": "assistant",
            "content": broken_response[:4000],
        },
        {"role": "user", "content": COMPACT_RETRY_PROMPT},
    ]


def _call_anthropic(settings: Settings, user_content: str, system_prompt: str) -> dict:
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
                "messages": [{"role": "user", "content": user_content}],
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
        payload = response.json()
        content = payload["content"][0]["text"]
        stop_reason = payload.get("stop_reason")

        try:
            return _parse_llm_content(content, provider="anthropic", stop_reason=stop_reason)
        except LLMJSONError:
            retry = httpx.post(
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
                    "messages": _retry_messages(user_content, content),
                },
                timeout=180.0,
            )
            retry.raise_for_status()
            retry_payload = retry.json()
            retry_content = retry_payload["content"][0]["text"]
            return _parse_llm_content(
                retry_content,
                provider="anthropic",
                stop_reason=retry_payload.get("stop_reason"),
            )

    if last_error is not None:
        raise last_error
    raise RuntimeError("No Anthropic models available to try")


def _call_openrouter(settings: Settings, user_content: str, system_prompt: str) -> dict:
    last_error: httpx.HTTPStatusError | None = None
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    for model in openrouter_model_candidates(settings.claude_model):
        response = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/TheMitchyBoy/Claude-LLM-Local-News-Analysis-",
                "X-Title": "Meeting Video Ideas Pipeline",
            },
            json={
                "model": model,
                "messages": messages,
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
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        finish_reason = payload["choices"][0].get("finish_reason")

        try:
            return _parse_llm_content(content, provider="openrouter", stop_reason=finish_reason)
        except LLMJSONError:
            retry_messages = messages + [
                {"role": "assistant", "content": content[:4000]},
                {"role": "user", "content": COMPACT_RETRY_PROMPT},
            ]
            retry = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": retry_messages,
                    "max_tokens": settings.llm_max_tokens,
                },
                timeout=180.0,
            )
            retry.raise_for_status()
            retry_content = retry.json()["choices"][0]["message"]["content"]
            return parse_llm_json(retry_content)

    if last_error is not None:
        raise last_error
    raise RuntimeError("No OpenRouter models available to try")


def _call_openai(settings: Settings, user_content: str, system_prompt: str) -> dict:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.openai_fallback_model,
            "messages": messages,
            "max_tokens": settings.llm_max_tokens,
            "response_format": {"type": "json_object"},
        },
        timeout=180.0,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return parse_llm_json(content)
