from __future__ import annotations

import json
import re

import httpx

from src.config import Settings
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

Produce 3-5 ideas per meeting when material supports it. Avoid duplicate angles."""

SYSTEM_PROMPT = BASE_SYSTEM_PROMPT


def get_system_prompt(guidance: dict | None = None) -> str:
    extra = build_guidance_prompt(guidance)
    return f"{BASE_SYSTEM_PROMPT}\n\nProducer preferences:\n{extra}"


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def analyze_transcripts(
    settings: Settings,
    transcripts: list[dict],
    guidance: dict | None = None,
) -> dict:
    user_content = "Analyze these meeting transcripts and suggest video topics:\n\n"
    for item in transcripts:
        user_content += f"---\nMEETING: {item['title']}\n"
        if item.get("meeting_type"):
            user_content += f"TYPE: {item['meeting_type']}\n"
        if item.get("published_at"):
            user_content += f"DATE: {item['published_at']}\n"
        user_content += f"TRANSCRIPT:\n{item['text']}\n\n"

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
            errors.append(f"{provider}: HTTP {exc.response.status_code}")
        except Exception as exc:
            errors.append(f"{provider}: {exc}")

    raise RuntimeError("All LLM providers failed: " + "; ".join(errors))


def _call_anthropic(settings: Settings, user_content: str, system_prompt: str) -> dict:
    model = settings.claude_model.removeprefix("anthropic/")
    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_content}],
        },
        timeout=120.0,
    )
    response.raise_for_status()
    content = response.json()["content"][0]["text"]
    return _extract_json(content)


def _call_openrouter(settings: Settings, user_content: str, system_prompt: str) -> dict:
    model = settings.claude_model
    if not model.startswith("anthropic/"):
        model = f"anthropic/{model}"

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
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": 4096,
        },
        timeout=120.0,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return _extract_json(content)


def _call_openai(settings: Settings, user_content: str, system_prompt: str) -> dict:
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.openai_fallback_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": 4096,
        },
        timeout=120.0,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return _extract_json(content)
