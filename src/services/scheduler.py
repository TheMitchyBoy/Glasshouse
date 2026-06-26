"""APScheduler cron job for daily new-meeting detection.

Runs run_daily_scan() once per day at DAILY_SCAN_HOUR:DAILY_SCAN_MINUTE
in DAILY_SCAN_TIMEZONE. Started automatically with the web dashboard.
"""

from __future__ import annotations

import json
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import Settings, get_settings
from src.services.daily_scan import run_daily_scan

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def start_daily_scheduler(settings: Settings | None = None) -> None:
    global _scheduler
    settings = settings or get_settings()

    if not settings.daily_scan_enabled:
        logger.info("Daily scan scheduler disabled")
        return

    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone=settings.daily_scan_timezone)
    _scheduler.add_job(
        run_daily_scan,
        CronTrigger(hour=settings.daily_scan_hour, minute=settings.daily_scan_minute),
        kwargs={"settings": settings},
        id="daily_meeting_scan",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info(
        "Daily scan scheduled at %02d:%02d %s",
        settings.daily_scan_hour,
        settings.daily_scan_minute,
        settings.daily_scan_timezone,
    )


def stop_daily_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
