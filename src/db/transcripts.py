from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg2
import psycopg2.extras

from src.config import Settings
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


def get_connection(settings: Settings):
    return psycopg2.connect(settings.database_url)


def fetch_recent_meeting_transcripts(settings: Settings) -> list[MeetingTranscript]:
    schema = load_schema(settings)
    query = build_transcript_query(schema)

    t = schema.transcripts
    v = schema.videos
    
    # Determine if query has a date filter based on exact logic in build_transcript_query
    has_date_filter = False
    if v is None:
        # No videos table: check transcripts for date columns
        has_date_filter = t is not None and t.has("published_at", "uploaded_at", "created_at")
    else:
        # Videos table exists: check both tables
        has_date_filter = (v.has("published_at") or (t is not None and t.has("published_at", "uploaded_at")))
    
    # Build params tuple based on whether date filter exists
    params = (
        (settings.lookback_days, settings.max_transcripts)
        if has_date_filter
        else (settings.max_transcripts,)
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

