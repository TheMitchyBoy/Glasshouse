from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.config import get_settings
from src.db.schema import load_schema
from src.db.transcripts import fetch_recent_meeting_transcripts, get_connection
from src.llm.claude import get_system_prompt
from src.notifications.telegram import get_telegram_bot_info, test_telegram_connection
from src.services.pipeline import load_latest_analysis, run_pipeline
from src.services.prompt_settings import load_guidance, save_guidance

router = APIRouter()


@router.get("/health")
def health():
    return {"ok": True}


class GuidanceUpdate(BaseModel):
    tone: str = ""
    audience: str = ""
    topics_to_prioritize: str = ""
    topics_to_avoid: str = ""
    custom_guidance: str = ""
    ideas_per_meeting: int = Field(default=4, ge=1, le=10)


class AnalyzeRequest(BaseModel):
    dry_run: bool = True
    send_telegram: bool = False
    guidance: GuidanceUpdate | None = None


class TelegramTestRequest(BaseModel):
    message: str | None = None


@router.get("/status")
def get_status():
    settings = get_settings()

    db_ok = False
    db_error = None
    transcript_count = 0
    try:
        with get_connection(settings):
            db_ok = True
        schema = load_schema(settings)
        transcript_count = len(fetch_recent_meeting_transcripts(settings))
    except Exception as exc:
        db_error = str(exc)

    llm_providers: list[str] = []
    llm_error = None
    try:
        llm_providers = settings.llm_providers
    except ValueError as exc:
        llm_error = str(exc)

    telegram_configured = settings.telegram_configured
    telegram_bot = None
    telegram_error = None
    if telegram_configured:
        try:
            telegram_bot = get_telegram_bot_info(settings.telegram_bot_token)
        except Exception as exc:
            telegram_error = str(exc)

    latest = load_latest_analysis()

    return {
        "database": {
            "connected": db_ok,
            "error": db_error,
            "meeting_transcripts": transcript_count,
        },
        "llm": {
            "providers": llm_providers,
            "model": settings.claude_model,
            "error": llm_error,
        },
        "telegram": {
            "configured": telegram_configured,
            "chat_id": settings.telegram_chat_id or None,
            "bot": telegram_bot,
            "error": telegram_error,
        },
        "latest_analysis": {
            "available": latest is not None,
            "idea_count": len(latest.get("ideas", [])) if latest else 0,
            "summary": latest.get("summary") if latest else None,
        },
    }


@router.get("/guidance")
def get_guidance():
    guidance = load_guidance()
    return {
        "guidance": guidance,
        "effective_prompt": get_system_prompt(guidance),
    }


@router.put("/guidance")
def update_guidance(payload: GuidanceUpdate):
    saved = save_guidance(payload.model_dump())
    return {
        "guidance": saved,
        "effective_prompt": get_system_prompt(saved),
    }


@router.post("/telegram/test")
def telegram_test(payload: TelegramTestRequest | None = None):
    settings = get_settings()
    if not settings.telegram_configured:
        raise HTTPException(status_code=400, detail="Telegram is not configured in environment variables.")

    try:
        if payload and payload.message:
            from src.notifications.telegram import send_telegram_message

            bot = get_telegram_bot_info(settings.telegram_bot_token)
            sent = send_telegram_message(
                settings.telegram_bot_token,
                settings.telegram_chat_id,
                payload.message,
            )
            return {
                "ok": sent,
                "bot_username": bot.get("username"),
                "bot_name": bot.get("first_name"),
                "chat_id": settings.telegram_chat_id,
                "message": "Custom test message sent.",
            }

        return test_telegram_connection(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
        )
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text
        raise HTTPException(status_code=502, detail=f"Telegram API error: {detail}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/analyze")
def analyze(payload: AnalyzeRequest):
    settings = get_settings()
    guidance = payload.guidance.model_dump() if payload.guidance else load_guidance()

    try:
        result = run_pipeline(
            settings,
            dry_run=payload.dry_run,
            send_telegram=payload.send_telegram,
            guidance=guidance,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "transcript_count": result.transcript_count,
        "idea_count": result.idea_count,
        "telegram_sent": result.telegram_sent,
        "run_id": result.run_id,
        "analysis": result.analysis,
        "telegram_preview": result.telegram_preview,
    }


@router.get("/ideas/latest")
def latest_ideas():
    analysis = load_latest_analysis()
    if not analysis:
        raise HTTPException(status_code=404, detail="No analysis results yet.")
    return analysis
