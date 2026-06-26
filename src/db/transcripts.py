"""Fetch meeting transcripts from PostgreSQL.

Queries are built dynamically by schema.py to support different
database layouts (with or without a videos table, text vs integer IDs).

Key functions:
  fetch_recent_meeting_transcripts  — all meetings in the lookback window
  fetch_unprocessed_meeting_transcripts — only meetings not yet analyzed
  fetch_latest_meeting_transcript   — single most recent meeting
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg2
import psycopg2.extras

from src.config import Settings
from src.db.connection import get_connection
from src.db.processed import get_processed_transcript_ids
from src.db.schema import build_transcript_query, load_schema


@dataclass
class MeetingTranscript:
    transcript_id: int
    video_id: str
    title: str
    meeting_type: str | None
    published_at: datetime | None
    full_text: str
    word_count: int


def fetch_recent_meeting_transcripts(settings: Settings) -> list[MeetingTranscript]:
    schema = load_schema(settings)
    query, params = build_transcript_query(
        schema,
        settings.lookback_days,
        settings.max_transcripts,
    )

    with get_connection(settings) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    return [
        MeetingTranscript(
            transcript_id=row["transcript_id"],
            video_id=str(row["video_id"]),
            title=row["title"] or str(row["video_id"]),
            meeting_type=row.get("meeting_type"),
            published_at=row.get("published_at"),
            full_text=row["full_text"],
            word_count=int(row["word_count"] or 0),
        )
        for row in rows
    ]


def fetch_unprocessed_meeting_transcripts(settings: Settings) -> list[MeetingTranscript]:
    processed_ids = get_processed_transcript_ids(settings)
    return [
        transcript
        for transcript in fetch_recent_meeting_transcripts(settings)
        if transcript.transcript_id not in processed_ids
    ]


def fetch_latest_meeting_transcript(settings: Settings) -> MeetingTranscript | None:
    transcripts = fetch_recent_meeting_transcripts(settings)
    return transcripts[0] if transcripts else None


def save_analysis_run(
    settings: Settings,
    transcript_ids: list[int],
    ideas_json: dict,
    telegram_sent: bool,
) -> int | None:
    schema = load_schema(settings)
    if "analysis_runs" not in schema.tables:
        return None

    query = """
        INSERT INTO analysis_runs (transcripts, ideas_json, telegram_sent)
        VALUES (%s, %s, %s)
        RETURNING id
    """
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (transcript_ids, psycopg2.extras.Json(ideas_json), telegram_sent),
            )
            run_id = cur.fetchone()[0]
        conn.commit()
    return run_id

