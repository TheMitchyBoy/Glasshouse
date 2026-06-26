"""Daily scan: find new meeting transcripts and notify via Telegram.

Called by the APScheduler cron job and by POST /api/scan/daily.
Only processes transcripts not already in processed_transcripts.
"""

from __future__ import annotations

import logging

from src.config import Settings, get_settings
from src.services.pipeline import run_pipeline_for_new_meetings

logger = logging.getLogger(__name__)


def run_daily_scan(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()

    if not settings.telegram_configured:
        logger.warning("Daily scan skipped: Telegram is not configured.")
        return {"ok": False, "reason": "telegram_not_configured", "new_meetings": 0}

    try:
        result = run_pipeline_for_new_meetings(settings, send_telegram=True)
    except Exception as exc:
        logger.exception("Daily scan failed")
        return {"ok": False, "reason": str(exc), "new_meetings": 0}

    if result is None:
        logger.info("Daily scan: no new meeting transcripts.")
        return {"ok": True, "new_meetings": 0, "message": "No new meetings found."}

    logger.info(
        "Daily scan complete: %s new meeting(s), %s ideas, telegram_sent=%s",
        result.transcript_count,
        result.idea_count,
        result.telegram_sent,
    )
    return {
        "ok": True,
        "new_meetings": result.transcript_count,
        "idea_count": result.idea_count,
        "telegram_sent": result.telegram_sent,
        "run_id": result.run_id,
        "transcript_ids": result.transcript_ids,
    }
