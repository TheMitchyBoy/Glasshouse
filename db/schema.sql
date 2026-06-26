-- YouTube Transcript database schema
-- Run: psql $DATABASE_URL -f db/schema.sql

CREATE TABLE IF NOT EXISTS channels (
    id          SERIAL PRIMARY KEY,
    channel_id  TEXT NOT NULL UNIQUE,
    name        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS videos (
    id           SERIAL PRIMARY KEY,
    video_id     TEXT NOT NULL UNIQUE,
    channel_id   INTEGER REFERENCES channels(id),
    title        TEXT NOT NULL,
    description  TEXT,
    published_at TIMESTAMPTZ,
    duration_sec INTEGER,
    is_meeting   BOOLEAN NOT NULL DEFAULT FALSE,
    meeting_type TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS transcripts (
    id          SERIAL PRIMARY KEY,
    video_id    INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    language    TEXT NOT NULL DEFAULT 'en',
    full_text   TEXT NOT NULL,
    segments    JSONB,
    word_count  INTEGER,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (video_id, language)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id           SERIAL PRIMARY KEY,
    run_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    transcripts  INTEGER[] NOT NULL,
    ideas_json   JSONB NOT NULL,
    telegram_sent BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_videos_published ON videos(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_videos_meeting ON videos(is_meeting) WHERE is_meeting = TRUE;
CREATE INDEX IF NOT EXISTS idx_transcripts_video ON transcripts(video_id);

CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
