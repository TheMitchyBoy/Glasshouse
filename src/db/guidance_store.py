"""Persist producer AI guidance in PostgreSQL.

Guidance (tone, audience, topic preferences) is stored in app_settings
so it survives Railway redeploys. Falls back to config/ai_guidance.json
locally if the database is unavailable.
"""

from __future__ import annotations

import json
from datetime import datetime

import psycopg2.extras

from src.config import Settings, get_settings
from src.db.connection import get_connection

GUIDANCE_KEY = "producer_guidance"

ENSURE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def _ensure_table(settings: Settings) -> None:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(ENSURE_TABLE_SQL)
        conn.commit()


def load_guidance_from_db(settings: Settings | None = None) -> dict | None:
    settings = settings or get_settings()
    try:
        _ensure_table(settings)
        with get_connection(settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT value, updated_at FROM app_settings WHERE key = %s",
                    (GUIDANCE_KEY,),
                )
                row = cur.fetchone()
        if not row:
            return None
        value, updated_at = row
        if isinstance(value, str):
            data = json.loads(value)
        else:
            data = dict(value)
        data["_saved_at"] = updated_at.isoformat() if isinstance(updated_at, datetime) else str(updated_at)
        return data
    except Exception:
        return None


def save_guidance_to_db(data: dict, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    payload = {k: v for k, v in data.items() if not k.startswith("_")}
    _ensure_table(settings)
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value, updated_at = NOW()
                RETURNING value, updated_at
                """,
                (GUIDANCE_KEY, psycopg2.extras.Json(payload)),
            )
            value, updated_at = cur.fetchone()
        conn.commit()

    saved = dict(value) if not isinstance(value, str) else json.loads(value)
    saved["_saved_at"] = updated_at.isoformat() if isinstance(updated_at, datetime) else str(updated_at)
    return saved
