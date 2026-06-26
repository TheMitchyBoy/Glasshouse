"""Conversational AI agent for Telegram Q&A about meetings.

Builds context from the latest meeting transcript, recent meetings list,
and saved video-ideas analysis. Maintains per-chat conversation history
so follow-up questions work naturally.
"""

from __future__ import annotations

import json
from collections import deque
from threading import Lock

from src.config import Settings, get_settings
from src.db.transcripts import fetch_latest_meeting_transcript, fetch_recent_meeting_transcripts
from src.llm.chat import chat_completion
from src.services.pipeline import load_latest_analysis
from src.services.prompt_settings import build_guidance_prompt, load_guidance

AGENT_SYSTEM_PROMPT = """You are a local news AI research assistant helping a video producer cover government meetings.

You have meeting transcripts and prior video-idea analysis in your context. Use them to:
- Answer questions about what was discussed, decided, or debated
- Explain budget impacts, controversial votes, and community concerns
- Suggest video angles, hooks, and follow-up reporting leads
- Summarize meetings in plain language for a local audience

Rules:
- Ground answers in the provided meeting context. If something is not in the transcripts, say you do not have that information.
- Be concise and practical — responses go to Telegram (aim for under 2500 characters).
- Use Telegram HTML only: <b>bold</b>, <i>italic</i>, and bullet lines starting with •
- Do not use markdown code fences or ### headers."""

_history_lock = Lock()
_conversations: dict[str, deque[dict[str, str]]] = {}


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[... truncated ...]"


def build_meeting_context(settings: Settings) -> str:
    sections: list[str] = []

    latest = fetch_latest_meeting_transcript(settings)
    if latest:
        date = latest.published_at.isoformat() if latest.published_at else "unknown"
        sections.append(
            "LATEST MEETING\n"
            f"Title: {latest.title}\n"
            f"Type: {latest.meeting_type or 'meeting'}\n"
            f"Date: {date}\n"
            f"Transcript:\n{_truncate(latest.full_text, settings.agent_context_chars)}"
        )

    recent = fetch_recent_meeting_transcripts(settings)[: settings.agent_recent_meetings]
    if len(recent) > 1:
        lines = [f"- {item.title} ({item.published_at or 'no date'})" for item in recent[1:]]
        sections.append("OTHER RECENT MEETINGS\n" + "\n".join(lines))

    analysis = load_latest_analysis()
    if analysis:
        sections.append(
            "LATEST VIDEO IDEAS ANALYSIS\n"
            + _truncate(json.dumps(analysis, indent=2), settings.agent_analysis_chars)
        )

    if not sections:
        return "No meeting transcripts are available in the database yet."

    return "\n\n---\n\n".join(sections)


def _get_history(chat_id: str, settings: Settings) -> deque[dict[str, str]]:
    with _history_lock:
        if chat_id not in _conversations:
            _conversations[chat_id] = deque(maxlen=settings.agent_max_history * 2)
        return _conversations[chat_id]


def clear_conversation(chat_id: str) -> None:
    with _history_lock:
        _conversations.pop(chat_id, None)


def answer_question(
    question: str,
    chat_id: str,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    guidance = load_guidance()
    context = build_meeting_context(settings)

    system_prompt = (
        f"{AGENT_SYSTEM_PROMPT}\n\n"
        f"Producer preferences:\n{build_guidance_prompt(guidance)}\n\n"
        f"MEETING CONTEXT:\n{context}"
    )

    history = _get_history(chat_id, settings)
    messages = list(history)
    messages.append({"role": "user", "content": question})

    reply = chat_completion(settings, system_prompt, messages)

    with _history_lock:
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": reply})

    return reply.strip()
