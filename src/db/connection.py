"""PostgreSQL connection helper.

Single place for database connections so other modules avoid
circular imports between transcripts, schema, and guidance_store.
"""

from __future__ import annotations

import psycopg2

from src.config import Settings


def get_connection(settings: Settings):
    return psycopg2.connect(settings.database_url)
