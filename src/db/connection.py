"""PostgreSQL connection helper.

Single place for database connections so other modules avoid
circular imports between transcripts, schema, and guidance_store.
"""

from __future__ import annotations

import psycopg2

from src.config import Settings


def get_connection(settings: Settings):
    database_url = settings.database_url
    if settings.is_production and "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"
    return psycopg2.connect(database_url)
