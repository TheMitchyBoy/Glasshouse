#!/usr/bin/env python3
"""One-shot CLI: analyze recent meetings and send video ideas via Telegram.

Analyzes all meetings in the LOOKBACK_DAYS window (not just new ones).
For daily new-meeting detection, use run_daily_scan.py instead.

Usage:
    python run_pipeline.py            # analyze + send Telegram
    python run_pipeline.py --dry-run  # preview without sending
"""

from __future__ import annotations

import argparse

from src.config import get_settings
from src.services.pipeline import run_pipeline


def run(dry_run: bool | None = None) -> int:
    settings = get_settings()
    if dry_run is not None:
        settings.dry_run = dry_run

    print(f"Fetching meeting transcripts (last {settings.lookback_days} days)...")
    try:
        result = run_pipeline(settings, dry_run=settings.dry_run)
    except ValueError as exc:
        print(str(exc))
        return 0

    print(f"Found {result.transcript_count} transcript(s).")
    print(f"Generated {result.idea_count} idea(s).")
    print(f"Saved full analysis to {result.output_path}")

    if settings.dry_run:
        print("\n--- DRY RUN: Telegram message preview ---\n")
        print(
            result.telegram_preview.replace("<b>", "**")
            .replace("</b>", "**")
            .replace("<i>", "_")
            .replace("</i>", "_")
        )
    elif result.telegram_sent:
        print("Telegram notification sent.")
    else:
        print("Telegram not configured (set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID).")
        print("\n--- Message preview ---\n")
        print(result.telegram_preview)

    if result.run_id is not None:
        print(f"Recorded analysis run #{result.run_id}.")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Meeting transcript → video ideas → Telegram")
    parser.add_argument("--dry-run", action="store_true", help="Skip Telegram, print preview")
    args = parser.parse_args()
    raise SystemExit(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
