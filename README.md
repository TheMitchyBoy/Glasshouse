# Claude LLM Local News Analysis

Analyze YouTube meeting transcripts from PostgreSQL, use **Claude** to suggest video topic ideas, run background web research, and deliver summaries via **Telegram**.

## Pipeline

```mermaid
flowchart LR
    PG[(PostgreSQL<br/>youtube_transcripts)] --> Fetch[Fetch meeting transcripts]
    Fetch --> Claude[Claude API<br/>topic ideas]
    Claude --> Research[Web background research]
    Research --> TG[Telegram notification]
    Research --> JSON[output/latest_ideas.json]
```

## Quick start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Start PostgreSQL (local dev)

```bash
docker compose up -d
```

This creates the `youtube_transcripts` database with schema and sample meeting data.

### 3. Configure environment

```bash
cp .env.example .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `ANTHROPIC_API_KEY` | One of | Direct Claude API key (preferred) |
| `OPENROUTER_API_KEY` | One of | Claude via OpenRouter |
| `OPENAI_API_KEY` | One of | Fallback if Claude providers unavailable |
| `CLAUDE_MODEL` | No | Default: `anthropic/claude-sonnet-4.5` |
| `TELEGRAM_BOT_TOKEN` | For notifications | From [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | For notifications | Your chat or group ID |
| `LOOKBACK_DAYS` | No | How far back to fetch meetings (default 14) |
| `MAX_TRANSCRIPTS` | No | Max transcripts per run (default 10) |

### 4. Run the pipeline

```bash
python run_pipeline.py
```

Preview without sending Telegram:

```bash
python run_pipeline.py --dry-run
```

### 5. Web dashboard

Start the dashboard to test Telegram, edit AI guidance, and preview generated ideas:

```bash
python run_dashboard.py
```

Open [http://localhost:8080](http://localhost:8080)

Dashboard features:
- Connection status for database, LLM, and Telegram
- Send a Telegram test message
- Save producer guidance that is injected into the Claude system prompt
- Run analysis and preview ideas without leaving the browser

## Database schema

Tables: `channels`, `videos`, `transcripts`, `analysis_runs`.

Mark videos as meetings with `is_meeting = TRUE`. Transcripts live in `transcripts.full_text`.

```sql
INSERT INTO videos (video_id, title, is_meeting, meeting_type, published_at)
VALUES ('abc123', 'County Commissioners - Jan 2025', TRUE, 'county_commission', NOW());

INSERT INTO transcripts (video_id, full_text)
VALUES (
  (SELECT id FROM videos WHERE video_id = 'abc123'),
  'Full transcript text here...'
);
```

## Scheduling

Run on a cron schedule after new meetings are transcribed:

```cron
0 8 * * 1 cd /path/to/repo && /path/to/venv/bin/python run_pipeline.py
```

## Output

- **Telegram**: HTML-formatted summary with titles, hooks, key points, and research snippets
- **JSON**: `output/latest_ideas.json` with full structured ideas and research results
- **Database**: `analysis_runs` table records each execution

## Project layout

```
config/
  ai_guidance.json    # Saved AI producer guidance
db/
  schema.sql          # PostgreSQL schema
  seed.sql            # Sample meeting data
frontend/
  index.html          # Web dashboard UI
src/
  api/                # FastAPI routes
  config.py           # Environment settings
  db/transcripts.py   # Transcript queries
  llm/claude.py       # Claude analysis
  services/           # Pipeline + prompt settings
  research/web_search.py
  notifications/telegram.py
run_pipeline.py       # CLI entry point
run_dashboard.py      # Web dashboard server
```
