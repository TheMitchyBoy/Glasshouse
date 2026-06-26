#!/usr/bin/env python3
"""Analyze meeting transcripts and send video topic ideas via Telegram."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.config import get_settings
from src.db.transcripts import fetch_recent_meeting_transcripts, save_analysis_run
from src.llm.claude import analyze_transcripts
from src.notifications.telegram import format_ideas_message, send_telegram_message
from src.research.web_search import enrich_ideas_with_research


def run(dry_run: bool | None = None) -> int:
    settings = get_settings()
    if dry_run is not None:
        settings.dry_run = dry_run

    print(f"Fetching meeting transcripts (last {settings.lookback_days} days)...")
    transcripts = fetch_recent_meeting_transcripts(settings)

    if not transcripts:
        print("No meeting transcripts found. Populate the database or widen LOOKBACK_DAYS.")
        return 0

    print(f"Found {len(transcripts)} transcript(s).")
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

    print(f"Analyzing with LLM ({', '.join(settings.llm_providers)})...")
    analysis = analyze_transcripts(settings, payload)
    ideas = analysis.get("ideas", [])
    summary = analysis.get("summary", "Video topic ideas from recent meetings.")

    print(f"Generated {len(ideas)} idea(s). Running background research...")
    ideas = enrich_ideas_with_research(ideas, settings.max_research_queries)
    analysis["ideas"] = ideas

    output_path = ROOT / "output" / "latest_ideas.json"
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    print(f"Saved full analysis to {output_path}")

    message = format_ideas_message(summary, ideas)
    telegram_sent = False

    if settings.dry_run:
        print("\n--- DRY RUN: Telegram message preview ---\n")
        print(message.replace("<b>", "**").replace("</b>", "**").replace("<i>", "_").replace("</i>", "_"))
    elif settings.telegram_configured:
        print("Sending Telegram notification...")
        send_telegram_message(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            message,
        )
        telegram_sent = True
        print("Telegram notification sent.")
    else:
        print("Telegram not configured (set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID).")
        print("\n--- Message preview ---\n")
        print(message)

    transcript_ids = [t.transcript_id for t in transcripts]
    run_id = save_analysis_run(settings, transcript_ids, analysis, telegram_sent)
    if run_id is not None:
        print(f"Recorded analysis run #{run_id}.")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Meeting transcript → video ideas → Telegram")
    parser.add_argument("--dry-run", action="store_true", help="Skip Telegram, print preview")
    args = parser.parse_args()
    raise SystemExit(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
