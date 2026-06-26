"""Producer guidance: tone, audience, and topic preferences for the LLM.

Guidance is appended to Claude's system prompt so every analysis reflects
your editorial style. Saved to Postgres via guidance_store.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.config import get_settings
from src.db.guidance_store import load_guidance_from_db, save_guidance_to_db

DEFAULT_GUIDANCE = {
    "tone": "investigative but accessible",
    "audience": "local residents who want to understand how government decisions affect their daily lives",
    "topics_to_prioritize": "",
    "topics_to_avoid": "",
    "custom_guidance": "",
    "ideas_per_meeting": 4,
}

GUIDANCE_PATH = Path(__file__).resolve().parents[2] / "config" / "ai_guidance.json"
GUIDANCE_FIELDS = tuple(DEFAULT_GUIDANCE.keys())


def _merge_defaults(data: dict) -> dict:
    merged = dict(DEFAULT_GUIDANCE)
    merged.update({k: data.get(k, merged[k]) for k in GUIDANCE_FIELDS})
    return merged


def _strip_meta(data: dict) -> dict:
    return {k: v for k, v in data.items() if k in GUIDANCE_FIELDS}


def _load_from_file() -> dict | None:
    if not GUIDANCE_PATH.exists():
        return None
    data = json.loads(GUIDANCE_PATH.read_text(encoding="utf-8"))
    return _merge_defaults(data)


def _save_to_file(data: dict) -> dict:
    merged = _merge_defaults(data)
    GUIDANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    GUIDANCE_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return merged


def load_guidance() -> dict:
    settings = get_settings()
    db_data = load_guidance_from_db(settings)
    if db_data:
        return _merge_defaults(_strip_meta(db_data))

    file_data = _load_from_file()
    if file_data:
        try:
            save_guidance_to_db(file_data, settings)
        except Exception:
            pass
        return file_data

    return save_guidance(_merge_defaults(DEFAULT_GUIDANCE))


def save_guidance(data: dict) -> dict:
    merged = _merge_defaults(_strip_meta(data))
    settings = get_settings()

    try:
        saved = save_guidance_to_db(merged, settings)
        return _merge_defaults(_strip_meta(saved))
    except Exception:
        return _save_to_file(merged)


def build_guidance_prompt(guidance: dict | None = None) -> str:
    settings = _merge_defaults(_strip_meta(guidance or load_guidance()))
    parts = [
        f"Tone: {settings.get('tone', '').strip() or DEFAULT_GUIDANCE['tone']}.",
        f"Target audience: {settings.get('audience', '').strip() or DEFAULT_GUIDANCE['audience']}.",
    ]

    prioritize = settings.get("topics_to_prioritize", "").strip()
    if prioritize:
        parts.append(f"Prioritize these topics and angles: {prioritize}.")

    avoid = settings.get("topics_to_avoid", "").strip()
    if avoid:
        parts.append(f"Avoid or de-emphasize: {avoid}.")

    ideas_per_meeting = settings.get("ideas_per_meeting", DEFAULT_GUIDANCE["ideas_per_meeting"])
    parts.append(f"Aim for about {ideas_per_meeting} ideas per meeting when the material supports it.")

    custom = settings.get("custom_guidance", "").strip()
    if custom:
        parts.append(f"Additional producer guidance: {custom}")

    return "\n".join(parts)
