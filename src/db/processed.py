"""Track which meeting transcripts have already been analyzed.

The daily scan uses this to avoid re-analyzing old meetings and only
notify you when genuinely new transcripts appear in the database.
"""

from __future__ import annotations

import psycopg2.extras

from src.config import Settings, get_settings
from src.db.connection import get_connection

ENSURE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS processed_transcripts (
    transcript_id INTEGER PRIMARY KEY,
    processed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    analysis_run_id INTEGER
)
"""


def _ensure_table(settings: Settings) -> None:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(ENSURE_TABLE_SQL)
            cur.execute(
                """
                INSERT INTO processed_transcripts (transcript_id, processed_at, analysis_run_id)
                SELECT DISTINCT unnest(transcripts), run_at, id
                FROM analysis_runs
                ON CONFLICT (transcript_id) DO NOTHING
                """
            )
        conn.commit()


def get_processed_transcript_ids(settings: Settings | None = None) -> set[int]:
    settings = settings or get_settings()
    try:
        _ensure_table(settings)
        with get_connection(settings) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT transcript_id FROM processed_transcripts")
                return {row[0] for row in cur.fetchall()}
    except Exception:
        return set()


def mark_transcripts_processed(
    transcript_ids: list[int],
    settings: Settings | None = None,
    analysis_run_id: int | None = None,
) -> None:
    if not transcript_ids:
        return

    settings = settings or get_settings()
    _ensure_table(settings)
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            for transcript_id in transcript_ids:
                cur.execute(
                    """
                    INSERT INTO processed_transcripts (transcript_id, analysis_run_id)
                    VALUES (%s, %s)
                    ON CONFLICT (transcript_id) DO UPDATE
                    SET processed_at = NOW(), analysis_run_id = EXCLUDED.analysis_run_id
                    """,
                    (transcript_id, analysis_run_id),
                )
        conn.commit()
