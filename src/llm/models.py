"""Map OpenRouter model slugs to Anthropic API model IDs.

OpenRouter uses dots (claude-sonnet-4.5) while Anthropic uses hyphens
(claude-sonnet-4-5). Also defines fallback model chains per provider.
"""

from __future__ import annotations

ANTHROPIC_FALLBACK_MODELS = [
    "claude-sonnet-4-5",
    "claude-sonnet-4-5-20250929",
    "claude-3-5-sonnet-20241022",
]

OPENROUTER_FALLBACK_MODELS = [
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-sonnet-4-5",
    "anthropic/claude-3.5-sonnet",
]


def normalize_anthropic_model(model: str) -> str:
    """Map OpenRouter-style model slugs to Anthropic API model IDs."""
    model = model.removeprefix("anthropic/").strip()
    # OpenRouter uses dots in minor versions: claude-sonnet-4.5
    if "." in model and model.startswith("claude-"):
        model = model.replace(".", "-")
    return model


def anthropic_model_candidates(model: str) -> list[str]:
    primary = normalize_anthropic_model(model)
    candidates = [primary, *ANTHROPIC_FALLBACK_MODELS]
    return list(dict.fromkeys(candidates))


def openrouter_model_candidates(model: str) -> list[str]:
    primary = model if model.startswith("anthropic/") else f"anthropic/{model}"
    candidates = [primary, *OPENROUTER_FALLBACK_MODELS]
    return list(dict.fromkeys(candidates))
