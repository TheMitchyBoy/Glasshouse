from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.config import Settings, get_settings
from src.db.transcripts import fetch_recent_meeting_transcripts, save_analysis_run
from src.llm.claude import analyze_transcripts
from src.notifications.telegram import format_ideas_message, send_telegram_message
from src.research.web_search import enrich_ideas_with_research
from src.services.prompt_settings import load_guidance

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = ROOT / "output" / "latest_ideas.json"


@dataclass
class PipelineResult:
    transcript_count: int
    idea_count: int
    analysis: dict
    telegram_sent: bool
    telegram_preview: str
    run_id: int | None
    output_path: str


def run_pipeline(
    settings: Settings | None = None,
    *,
    dry_run: bool = False,
    send_telegram: bool | None = None,
    guidance: dict | None = None,
) -> PipelineResult:
    settings = settings or get_settings()
    guidance = guidance or load_guidance()

    transcripts = fetch_recent_meeting_transcripts(settings)
    if not transcripts:
        raise ValueError("No meeting transcripts found. Populate the database or widen LOOKBACK_DAYS.")

    payload = [
        {
            "transcript_id": t.transcript_id,
            "title": t.title,
            "meeting_type": t.meeting_type,
            "published_at": t.published_at.isoformat() if t.published_at else None,
            "text": t.full_text,
        }
        for t in transcripts
    ]

    analysis = analyze_transcripts(settings, payload, guidance=guidance)
    ideas = analysis.get("ideas", [])
    summary = analysis.get("summary", "Video topic ideas from recent meetings.")

    ideas = enrich_ideas_with_research(ideas, settings.max_research_queries)
    analysis["ideas"] = ideas

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(analysis, indent=2), encoding="utf-8")

    message = format_ideas_message(summary, ideas)
    should_send = send_telegram if send_telegram is not None else not dry_run
    telegram_sent = False

    if should_send and settings.telegram_configured:
        send_telegram_message(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            message,
        )
        telegram_sent = True

    transcript_ids = [t.transcript_id for t in transcripts]
    run_id = save_analysis_run(settings, transcript_ids, analysis, telegram_sent)

    return PipelineResult(
        transcript_count=len(transcripts),
        idea_count=len(ideas),
        analysis=analysis,
        telegram_sent=telegram_sent,
        telegram_preview=message,
        run_id=run_id,
        output_path=str(OUTPUT_PATH),
    )


def load_latest_analysis() -> dict | None:
    if not OUTPUT_PATH.exists():
        return None
    return json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
