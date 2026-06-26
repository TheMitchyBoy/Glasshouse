"""Parse and repair JSON returned by Claude.

LLM responses are sometimes truncated or malformed. This module strips
markdown fences, extracts the JSON object, and uses json-repair as fallback.
"""
from __future__ import annotations

import json
import re

try:
    from json_repair import repair_json
except ImportError:  # pragma: no cover
    repair_json = None


class LLMJSONError(ValueError):
    pass


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_json_object(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    return text[start:]


def parse_llm_json(text: str) -> dict:
    cleaned = _strip_markdown_fences(text)
    candidates = [cleaned, _extract_json_object(cleaned) or ""]
    errors: list[str] = []

    for candidate in candidates:
        if not candidate:
            continue
        for attempt in (candidate, repair_json(candidate) if repair_json else None):
            if not attempt:
                continue
            try:
                data = json.loads(attempt)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError as exc:
                errors.append(str(exc))

    preview = cleaned[:240].replace("\n", " ")
    raise LLMJSONError(
        "Could not parse LLM JSON response"
        + (f" ({errors[-1]})" if errors else "")
        + f". Preview: {preview}…"
    )
