"""Main analysis pipeline: transcripts → Claude → research → Telegram.

Orchestrates the full flow from fetching meeting transcripts through
LLM analysis, web research enrichment, Telegram delivery, and recording
the run in Postgres.

Entry points:
  run_pipeline()                  — analyze all recent meetings (CLI)
  run_pipeline_for_new_meetings() — daily scan: unprocessed only
  run_pipeline_for_latest_meeting() — Telegram /latest command
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.config import Settings, get_settings
from src.db.processed import mark_transcripts_processed
from src.db.transcripts import (
    MeetingTranscript,
    fetch_latest_meeting_transcript,
    fetch_unprocessed_meeting_transcripts,
    save_analysis_run,
)
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
    transcript_ids: list[int]


def _transcripts_to_payload(transcripts: list[MeetingTranscript]) -> list[dict]:
    return [
        {
            "transcript_id": t.transcript_id,
            "title": t.title,
            "meeting_type": t.meeting_type,
            "published_at": t.published_at.isoformat() if t.published_at else None,
            "text": t.full_text,
        }
        for t in transcripts
    ]


def run_pipeline_for_transcripts(
    transcripts: list[MeetingTranscript],
    settings: Settings | None = None,
    *,
    dry_run: bool = False,
    send_telegram: bool | None = None,
    guidance: dict | None = None,
    mark_processed: bool = True,
) -> PipelineResult:
    if not transcripts:
        raise ValueError("No transcripts provided for analysis.")

    settings = settings or get_settings()
    guidance = guidance or load_guidance()
    payload = _transcripts_to_payload(transcripts)

    analysis = analyze_transcripts(settings, payload, guidance=guidance)
    ideas = analysis.get("ideas", [])
    summary = analysis.get("summary", "Video topic ideas from recent meetings.")

    ideas = enrich_ideas_with_research(ideas, settings.max_research_queries)
    analysis["ideas"] = ideas
    analysis["source_transcripts"] = [t.title for t in transcripts]

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

    if mark_processed:
        mark_transcripts_processed(transcript_ids, settings, run_id)

    return PipelineResult(
        transcript_count=len(transcripts),
        idea_count=len(ideas),
        analysis=analysis,
        telegram_sent=telegram_sent,
        telegram_preview=message,
        run_id=run_id,
        output_path=str(OUTPUT_PATH),
        transcript_ids=transcript_ids,
    )


def run_pipeline(
    settings: Settings | None = None,
    *,
    dry_run: bool = False,
    send_telegram: bool | None = None,
    guidance: dict | None = None,
) -> PipelineResult:
    settings = settings or get_settings()
    from src.db.transcripts import fetch_recent_meeting_transcripts

    transcripts = fetch_recent_meeting_transcripts(settings)
    if not transcripts:
        raise ValueError("No meeting transcripts found. Populate the database or widen LOOKBACK_DAYS.")

    return run_pipeline_for_transcripts(
        transcripts,
        settings,
        dry_run=dry_run,
        send_telegram=send_telegram,
        guidance=guidance,
        mark_processed=False,
    )


def run_pipeline_for_new_meetings(
    settings: Settings | None = None,
    *,
    send_telegram: bool = True,
) -> PipelineResult | None:
    settings = settings or get_settings()
    transcripts = fetch_unprocessed_meeting_transcripts(settings)
    if not transcripts:
        return None

    return run_pipeline_for_transcripts(
        transcripts,
        settings,
        send_telegram=send_telegram,
        mark_processed=True,
    )


def run_pipeline_for_latest_meeting(
    settings: Settings | None = None,
    *,
    send_telegram: bool = True,
    mark_processed: bool = False,
) -> PipelineResult:
    settings = settings or get_settings()
    latest = fetch_latest_meeting_transcript(settings)
    if not latest:
        raise ValueError("No meeting transcripts found.")

    return run_pipeline_for_transcripts(
        [latest],
        settings,
        send_telegram=send_telegram,
        mark_processed=mark_processed,
    )


def load_latest_analysis() -> dict | None:
    if not OUTPUT_PATH.exists():
        return None
    return json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
