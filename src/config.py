"""Application configuration loaded from environment variables.

All settings are defined in Settings and read from .env locally or
injected by Railway in production. See .env.example for the full list.

Provider priority for LLM calls is determined by which API keys are set:
Anthropic → OpenRouter → OpenAI.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/youtube_transcripts"

    anthropic_api_key: str = ""
    openrouter_api_key: str = ""
    openai_api_key: str = ""
    claude_model: str = "claude-sonnet-4-5"
    openai_fallback_model: str = "gpt-4o-mini"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    lookback_days: int = 14
    max_transcripts: int = 10
    max_research_queries: int = 3
    max_transcript_chars: int = 6000
    llm_max_tokens: int = 8192
    dry_run: bool = False

    daily_scan_enabled: bool = True
    daily_scan_hour: int = 8
    daily_scan_minute: int = 0
    daily_scan_timezone: str = "UTC"
    telegram_polling_enabled: bool = True

    agent_max_history: int = 8
    agent_context_chars: int = 8000
    agent_analysis_chars: int = 4000
    agent_recent_meetings: int = 5

    @property
    def llm_providers(self) -> list[str]:
        providers: list[str] = []
        if self.anthropic_api_key:
            providers.append("anthropic")
        if self.openrouter_api_key:
            providers.append("openrouter")
        if self.openai_api_key:
            providers.append("openai")
        if not providers:
            raise ValueError("Set ANTHROPIC_API_KEY, OPENROUTER_API_KEY, or OPENAI_API_KEY")
        return providers

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


def get_settings() -> Settings:
    return Settings()
