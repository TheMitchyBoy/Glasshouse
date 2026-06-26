# Architecture & code map

This document explains what each part of Glasshouse does and how data flows through the system.

---

## Entry points

| File | When to use |
|------|-------------|
| `run_dashboard.py` | **Primary.** Starts the web UI, daily scheduler, and Telegram bot. Use for Railway deploy and local dev. |
| `run_pipeline.py` | One-shot CLI: analyze all recent meetings and optionally send Telegram. Good for cron without the web server. |
| `run_daily_scan.py` | One-shot CLI: only analyze **new** (unprocessed) meetings. Used by the scheduler and manual triggers. |

---

## Data flow: video idea generation

```
PostgreSQL transcripts
    ↓  src/db/transcripts.py      — fetch meetings (schema-adaptive SQL)
    ↓  src/services/pipeline.py   — orchestrate the run
    ↓  src/llm/claude.py          — send transcripts to Claude, get JSON ideas
    ↓  src/research/web_search.py — DuckDuckGo enrichment per idea
    ↓  src/notifications/telegram.py — format and send HTML message
    ↓  output/latest_ideas.json   — saved artifact
    ↓  analysis_runs table        — run history in Postgres
```

### Key files

**`src/db/schema.py`** — Inspects your Postgres `information_schema` at runtime and builds the correct SQL for your transcript/video table layout. Handles schemas where `videos.video_id` is missing, transcripts-only tables, and integer vs text foreign keys.

**`src/db/transcripts.py`** — Fetches meeting transcripts:
- `fetch_recent_meeting_transcripts()` — all meetings in lookback window
- `fetch_unprocessed_meeting_transcripts()` — excludes IDs in `processed_transcripts`
- `fetch_latest_meeting_transcript()` — most recent meeting only

**`src/db/processed.py`** — Tracks which transcript IDs have been analyzed so the daily scan only processes **new** meetings.

**`src/services/pipeline.py`** — Main orchestrator:
- `run_pipeline_for_transcripts()` — analyze a specific list of meetings
- `run_pipeline_for_new_meetings()` — daily scan path (unprocessed only)
- `run_pipeline_for_latest_meeting()` — Telegram `/latest` command path

**`src/llm/claude.py`** — Structured analysis. Sends transcripts + producer guidance to Claude and expects JSON with `summary` and `ideas[]`. Includes retry logic for malformed JSON and model fallback chain.

**`src/llm/json_parse.py`** — Repairs truncated or malformed LLM JSON using `json-repair`.

**`src/llm/models.py`** — Maps OpenRouter model names (`claude-sonnet-4.5`) to Anthropic API IDs (`claude-sonnet-4-5`).

**`src/services/prompt_settings.py`** — Loads/saves producer guidance (tone, audience, topics) from Postgres `app_settings` table.

---

## Data flow: Telegram AI agent

```
User message in Telegram
    ↓  src/services/telegram_bot.py  — poll getUpdates, route commands vs questions
    ↓  src/services/meeting_agent.py  — build context + conversation history
    ↓  src/llm/chat.py                — plain-text Claude completion (not JSON)
    ↓  src/notifications/telegram.py  — send reply (splits long messages)
```

**`src/services/meeting_agent.py`** — Builds context from:
1. Latest meeting transcript (truncated to `AGENT_CONTEXT_CHARS`)
2. List of other recent meetings
3. Last saved video-ideas analysis JSON

Maintains per-chat conversation history (`AGENT_MAX_HISTORY` turns) for follow-up questions.

**`src/services/telegram_bot.py`** — Long-polling loop. Only responds to `TELEGRAM_CHAT_ID` for security. Routes:
- `/latest`, `/ideas` → full pipeline analysis
- `/reset` → clear agent memory
- Everything else → meeting agent Q&A

---

## Data flow: daily automation

```
APScheduler cron trigger (default 08:00 UTC)
    ↓  src/services/scheduler.py
    ↓  src/services/daily_scan.py
    ↓  src/services/pipeline.py → run_pipeline_for_new_meetings()
    ↓  Telegram notification if new meetings found
```

Scheduler and Telegram polling start automatically when FastAPI boots (`src/api/app.py` lifespan).

---

## Web dashboard

**`src/api/app.py`** — FastAPI application. Mounts API routes at `/api` and static frontend at `/`.

**`src/api/routes.py`** — REST endpoints for status, guidance, analysis, Telegram test, and manual scan.

**`frontend/`** — Single-page app (no build step). Calls `/api/*` endpoints for status, saving guidance, and running analysis.

---

## Configuration

**`src/config.py`** — All settings from environment variables via `pydantic-settings`. Reads `.env` file locally; Railway injects vars directly.

Provider priority for LLM calls: Anthropic → OpenRouter → OpenAI (first available wins).

---

## Database tables

| Table | Written by | Read by |
|-------|-----------|---------|
| `transcripts` | Your ingestion pipeline | `transcripts.py` |
| `videos` | Your ingestion pipeline | `schema.py` (joins) |
| `analysis_runs` | `pipeline.py` | `processed.py` (backfill) |
| `processed_transcripts` | `pipeline.py`, `processed.py` | `daily_scan.py` |
| `app_settings` | `guidance_store.py` | `prompt_settings.py` |

---

## Adding a new feature

| I want to… | Start here |
|------------|-----------|
| Change the LLM prompt for video ideas | `src/llm/claude.py` → `BASE_SYSTEM_PROMPT` |
| Change the Telegram agent personality | `src/services/meeting_agent.py` → `AGENT_SYSTEM_PROMPT` |
| Add a new API endpoint | `src/api/routes.py` |
| Add a new Telegram command | `src/services/telegram_bot.py` → `_handle_message()` |
| Support a new Postgres schema | `src/db/schema.py` → `build_transcript_query()` |
| Change daily scan schedule | `src/config.py` → `daily_scan_*` settings |
