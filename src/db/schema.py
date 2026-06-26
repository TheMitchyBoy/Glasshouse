"""Runtime Postgres schema detection and adaptive SQL generation.

Different YouTube transcript databases use different column names and
join patterns. This module inspects information_schema and builds the
correct SELECT query so Glasshouse works without manual schema config.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.config import Settings
from src.db.connection import get_connection


@dataclass
class TableColumns:
    name: str
    columns: dict[str, str] = field(default_factory=dict)

    def has(self, *names: str) -> bool:
        return any(name in self.columns for name in names)

    def pick(self, *names: str) -> str | None:
        for name in names:
            if name in self.columns:
                return name
        return None


@dataclass
class DatabaseSchema:
    tables: dict[str, TableColumns]

    @property
    def transcripts(self) -> TableColumns | None:
        return self.tables.get("transcripts")

    @property
    def videos(self) -> TableColumns | None:
        return self.tables.get("videos")


def load_schema(settings: Settings) -> DatabaseSchema:
    query = """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """
    tables: dict[str, TableColumns] = {}
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            for table_name, column_name, data_type in cur.fetchall():
                tables.setdefault(table_name, TableColumns(name=table_name))
                tables[table_name].columns[column_name] = data_type
    return DatabaseSchema(tables=tables)


def _text_expr(table_alias: str, column: str | None, fallback: str) -> str:
    if column:
        return f"{table_alias}.{column}"
    return fallback


def build_transcript_query(
    schema: DatabaseSchema,
    lookback_days: int,
    max_transcripts: int,
) -> tuple[str, tuple]:
    query = _build_transcript_query_sql(schema)
    uses_lookback = "%s || ' days'" in query
    params: list[int] = []
    if uses_lookback:
        params.append(lookback_days)
    params.append(max_transcripts)
    return query, tuple(params)


def _build_transcript_query_sql(schema: DatabaseSchema) -> str:
    t = schema.transcripts
    if t is None:
        raise RuntimeError("No transcripts table found in database")

    v = schema.videos

    transcript_id_col = t.pick("id", "transcript_id") or "id"
    text_col = t.pick("full_text", "text", "transcript", "content")
    if not text_col:
        raise RuntimeError("transcripts table is missing a text column")

    word_count_expr = (
        f"COALESCE(t.{t.pick('word_count')}, LENGTH(t.{text_col}) / 5)"
        if t.has("word_count")
        else f"LENGTH(t.{text_col}) / 5"
    )

    order_col = t.pick("fetched_at", "created_at", "updated_at", "id") or "id"

    if v is None:
        video_id_col = t.pick("video_id", "youtube_id", "yt_video_id")
        if not video_id_col:
            raise RuntimeError("transcripts table is missing video_id")

        title_expr = _text_expr("t", t.pick("title", "video_title"), f"t.{video_id_col}")
        meeting_type_expr = _text_expr("t", t.pick("meeting_type", "category"), "NULL")
        published_expr = _text_expr("t", t.pick("published_at", "uploaded_at", "created_at"), "NULL")

        meeting_filter = ""
        if t.has("is_meeting"):
            meeting_filter = "t.is_meeting = TRUE"
        elif t.has("meeting_type"):
            meeting_filter = "t.meeting_type IS NOT NULL"
        elif t.has("title", "video_title"):
            title_name = t.pick("title", "video_title")
# %% must be escaped as %%%% in ILIKE patterns when using psycopg2 parameterized queries
            meeting_filter = (
                f"(t.{title_name} ILIKE '%%meeting%%' OR t.{title_name} ILIKE '%%council%%' "
                f"OR t.{title_name} ILIKE '%%board%%' OR t.{title_name} ILIKE '%%commission%%')"
            )

        where_parts = []
        if meeting_filter:
            where_parts.append(meeting_filter)
        if t.has("published_at", "uploaded_at", "created_at"):
            pub = t.pick("published_at", "uploaded_at", "created_at")
            where_parts.append(
                f"(t.{pub} IS NULL OR t.{pub} >= NOW() - (%s || ' days')::INTERVAL)"
            )
        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

        return f"""
            SELECT
                t.{transcript_id_col} AS transcript_id,
                t.{video_id_col}::text AS video_id,
                {title_expr} AS title,
                {meeting_type_expr} AS meeting_type,
                {published_expr} AS published_at,
                t.{text_col} AS full_text,
                {word_count_expr} AS word_count
            FROM transcripts t
            {where_clause}
            ORDER BY {published_expr} DESC NULLS LAST, t.{order_col} DESC
            LIMIT %s
        """

    # videos table exists — detect join strategy
    t_video_id = t.pick("video_id", "youtube_id", "yt_video_id")
    if not t_video_id:
        raise RuntimeError("transcripts table is missing video_id")

    t_video_type = t.columns.get(t_video_id, "text")
    join_on_int_fk = t_video_type in {"integer", "bigint", "smallint"} and v.has("id")

    if join_on_int_fk:
        join_clause = f"JOIN videos v ON v.id = t.{t_video_id}"
        video_key = v.pick("video_id", "youtube_id", "yt_video_id")
        video_id_expr = f"v.{video_key}::text" if video_key else f"t.{t_video_id}::text"
    else:
        video_key = v.pick("video_id", "youtube_id", "yt_video_id", "id")
        if not video_key:
            raise RuntimeError("videos table is missing a joinable video id column")
        join_clause = f"LEFT JOIN videos v ON v.{video_key}::text = t.{t_video_id}::text"
        video_id_expr = f"COALESCE(v.{video_key}, t.{t_video_id})::text"

    title_expr = (
        f"COALESCE(v.{v.pick('title')}, t.{t.pick('title', 'video_title')}, {video_id_expr})"
        if v.has("title") and t.has("title", "video_title")
        else f"COALESCE(v.{v.pick('title')}, {video_id_expr})"
        if v.has("title")
        else _text_expr("t", t.pick("title", "video_title"), video_id_expr)
    )
    meeting_type_expr = (
        f"COALESCE(v.{v.pick('meeting_type')}, t.{t.pick('meeting_type')})"
        if v.has("meeting_type") and t.has("meeting_type")
        else _text_expr("v", v.pick("meeting_type"), "NULL")
        if v.has("meeting_type")
        else _text_expr("t", t.pick("meeting_type"), "NULL")
    )
    published_expr = (
        f"COALESCE(v.{v.pick('published_at')}, t.{t.pick('published_at', 'uploaded_at')})"
        if v.has("published_at") and t.has("published_at", "uploaded_at")
        else _text_expr("v", v.pick("published_at"), "NULL")
        if v.has("published_at")
        else _text_expr("t", t.pick("published_at", "uploaded_at"), "NULL")
    )

    where_parts = []
    if v.has("is_meeting"):
        where_parts.append("v.is_meeting = TRUE")
    elif t.has("is_meeting"):
        where_parts.append("t.is_meeting = TRUE")
    elif v.has("meeting_type"):
        where_parts.append("v.meeting_type IS NOT NULL")
    elif t.has("meeting_type"):
        where_parts.append("t.meeting_type IS NOT NULL")
    elif v.has("title"):
        where_parts.append(
            "(v.title ILIKE '%%meeting%%' OR v.title ILIKE '%%council%%' "
            "OR v.title ILIKE '%%board%%' OR v.title ILIKE '%%commission%%')"
        )

    if v.has("published_at") or t.has("published_at", "uploaded_at"):
        where_parts.append(
            f"({published_expr} IS NULL OR {published_expr} >= NOW() - (%s || ' days')::INTERVAL)"
        )

    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    return f"""
        SELECT
            t.{transcript_id_col} AS transcript_id,
            {video_id_expr} AS video_id,
            {title_expr} AS title,
            {meeting_type_expr} AS meeting_type,
            {published_expr} AS published_at,
            t.{text_col} AS full_text,
            {word_count_expr} AS word_count
        FROM transcripts t
        {join_clause}
        {where_clause}
        ORDER BY {published_expr} DESC NULLS LAST, t.{order_col} DESC
        LIMIT %s
    """
