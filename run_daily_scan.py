#!/usr/bin/env python3
"""Run the daily new-meeting scan once.

Checks for meeting transcripts not yet in processed_transcripts,
runs analysis, and sends Telegram if new meetings are found.

Used by:
  - APScheduler (automatic, via run_dashboard.py)
  - POST /api/scan/daily (manual trigger from dashboard)
  - External cron (set DAILY_SCAN_ENABLED=false and cron this script)

Usage:
    python run_daily_scan.py
"""

from src.services.daily_scan import run_daily_scan


def main() -> None:
    result = run_daily_scan()
    print(result)


if __name__ == "__main__":
    main()
