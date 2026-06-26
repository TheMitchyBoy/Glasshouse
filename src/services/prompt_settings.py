from __future__ import annotations

import json
from pathlib import Path

DEFAULT_GUIDANCE = {
    "tone": "investigative but accessible",
    "audience": "local residents who want to understand how government decisions affect their daily lives",
    "topics_to_prioritize": "",
    "topics_to_avoid": "",
    "custom_guidance": "",
    "ideas_per_meeting": 4,
}

GUIDANCE_PATH = Path(__file__).resolve().parents[2] / "config" / "ai_guidance.json"


def load_guidance() -> dict:
    if not GUIDANCE_PATH.exists():
        save_guidance(DEFAULT_GUIDANCE)
        return dict(DEFAULT_GUIDANCE)

    data = json.loads(GUIDANCE_PATH.read_text(encoding="utf-8"))
    merged = dict(DEFAULT_GUIDANCE)
    merged.update(data)
    return merged


def save_guidance(data: dict) -> dict:
    merged = dict(DEFAULT_GUIDANCE)
    merged.update(data)
    GUIDANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    GUIDANCE_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return merged


def build_guidance_prompt(guidance: dict | None = None) -> str:
    settings = guidance or load_guidance()
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
