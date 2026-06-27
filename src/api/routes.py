"""REST API routes for the web dashboard and automation triggers.

Endpoints let the dashboard check connections, save AI guidance,
run analysis, test Telegram, and manually trigger the daily scan.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.security import check_rate_limit, safe_error_detail, safe_status_error
from src.config import Settings, get_settings
from src.db.schema import load_schema
from src.db.transcripts import fetch_recent_meeting_transcripts, get_connection
from src.llm.claude import get_system_prompt
from src.notifications.telegram import escape_telegram_html, get_telegram_bot_info, send_telegram_message, test_telegram_connection
from src.services.daily_scan import run_daily_scan
from src.services.pipeline import load_latest_analysis, run_pipeline, run_pipeline_for_latest_meeting
from src.services.prompt_settings import load_guidance, save_guidance

router = APIRouter()


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/auth/required")
def auth_required():
    settings = get_settings()
    return {"required": bool(settings.api_secret_key)}


class GuidanceUpdate(BaseModel):
    tone: str = Field(default="", max_length=500)
    audience: str = Field(default="", max_length=500)
    topics_to_prioritize: str = Field(default="", max_length=2000)
    topics_to_avoid: str = Field(default="", max_length=2000)
    custom_guidance: str = Field(default="", max_length=2000)
    ideas_per_meeting: int = Field(default=4, ge=1, le=10)


class AnalyzeRequest(BaseModel):
    dry_run: bool = True
    send_telegram: bool = False
    guidance: GuidanceUpdate | None = None


class TelegramTestRequest(BaseModel):
    message: str | None = Field(default=None, max_length=1000)


def _guidance_response(guidance: dict, db_row: dict | None, settings: Settings) -> dict:
    response = {
        "guidance": guidance,
        "saved_at": db_row.get("_saved_at") if db_row else None,
        "storage": "database" if db_row else "file",
    }
    if not settings.is_production:
        response["effective_prompt"] = get_system_prompt(guidance)
    return response


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
        db_error = safe_status_error(exc, settings)

    llm_providers: list[str] = []
    llm_error = None
    try:
        llm_providers = settings.llm_providers
    except ValueError as exc:
        llm_error = safe_status_error(exc, settings)

    telegram_configured = settings.telegram_configured
    telegram_bot = None
    telegram_error = None
    if telegram_configured:
        try:
            telegram_bot = get_telegram_bot_info(settings.telegram_bot_token)
        except Exception as exc:
            telegram_error = safe_status_error(exc, settings)

    latest = load_latest_analysis()

    telegram_payload: dict = {
        "configured": telegram_configured,
        "error": telegram_error,
    }
    if telegram_bot:
        telegram_payload["bot_username"] = telegram_bot.get("username")
        if not settings.is_production:
            telegram_payload["bot"] = telegram_bot
            telegram_payload["chat_id"] = settings.telegram_chat_id or None

    return {
        "database": {
            "connected": db_ok,
            "error": db_error,
            "meeting_transcripts": transcript_count,
        },
        "llm": {
            "providers": llm_providers if not settings.is_production else ["configured" if llm_providers else "missing"],
            "model": settings.claude_model,
            "error": llm_error,
        },
        "telegram": telegram_payload,
        "latest_analysis": {
            "available": latest is not None,
            "idea_count": len(latest.get("ideas", [])) if latest else 0,
            "summary": latest.get("summary") if latest and not settings.is_production else None,
        },
        "automation": {
            "daily_scan_enabled": settings.daily_scan_enabled,
            "daily_scan_time": f"{settings.daily_scan_hour:02d}:{settings.daily_scan_minute:02d} {settings.daily_scan_timezone}",
            "telegram_polling_enabled": settings.telegram_polling_enabled,
        },
    }


@router.get("/guidance")
def get_guidance():
    settings = get_settings()
    guidance = load_guidance()
    db_row = None
    try:
        from src.db.guidance_store import load_guidance_from_db

        db_row = load_guidance_from_db()
    except Exception:
        pass
    return _guidance_response(guidance, db_row, settings)


@router.put("/guidance")
def update_guidance(payload: GuidanceUpdate):
    settings = get_settings()
    try:
        saved = save_guidance(payload.model_dump())
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save guidance: {safe_error_detail(exc, settings)}",
        ) from exc
    db_row = None
    try:
        from src.db.guidance_store import load_guidance_from_db

        db_row = load_guidance_from_db()
    except Exception:
        pass
    return _guidance_response(saved, db_row, settings)


@router.post("/telegram/test")
def telegram_test(payload: TelegramTestRequest | None = None):
    settings = get_settings()
    if not settings.telegram_configured:
        raise HTTPException(status_code=400, detail="Telegram is not configured in environment variables.")

    try:
        if payload and payload.message:
            bot = get_telegram_bot_info(settings.telegram_bot_token)
            safe_message = escape_telegram_html(payload.message)
            sent = send_telegram_message(
                settings.telegram_bot_token,
                settings.telegram_chat_id,
                safe_message,
            )
            response = {
                "ok": sent,
                "message": "Custom test message sent.",
            }
            if not settings.is_production:
                response.update(
                    {
                        "bot_username": bot.get("username"),
                        "bot_name": bot.get("first_name"),
                        "chat_id": settings.telegram_chat_id,
                    }
                )
            return response

        result = test_telegram_connection(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
        )
        if settings.is_production:
            return {"ok": result.get("ok", False), "message": "Telegram connection test sent."}
        return result
    except httpx.HTTPStatusError as exc:
        detail = safe_error_detail(exc, settings) if settings.is_production else exc.response.text
        raise HTTPException(status_code=502, detail=f"Telegram API error: {detail}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=safe_error_detail(exc, settings)) from exc


@router.post("/analyze")
def analyze(request: Request, payload: AnalyzeRequest):
    settings = get_settings()
    check_rate_limit(
        request,
        scope="analyze",
        limit=settings.rate_limit_analyze_per_minute,
    )

    if payload.guidance:
        guidance = save_guidance(payload.guidance.model_dump())
    else:
        guidance = load_guidance()

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
        raise HTTPException(status_code=502, detail=safe_error_detail(exc, settings)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=safe_error_detail(exc, settings)) from exc

    return {
        "transcript_count": result.transcript_count,
        "idea_count": result.idea_count,
        "telegram_sent": result.telegram_sent,
        "run_id": result.run_id,
        "analysis": result.analysis,
        "telegram_preview": result.telegram_preview,
    }


@router.post("/scan/daily")
def trigger_daily_scan(request: Request):
    settings = get_settings()
    check_rate_limit(
        request,
        scope="scan",
        limit=settings.rate_limit_scan_per_minute,
    )
    return run_daily_scan()


@router.post("/analyze/latest")
def analyze_latest(request: Request, payload: AnalyzeRequest | None = None):
    settings = get_settings()
    check_rate_limit(
        request,
        scope="analyze",
        limit=settings.rate_limit_analyze_per_minute,
    )

    body = payload or AnalyzeRequest()
    if body.guidance:
        save_guidance(body.guidance.model_dump())

    try:
        result = run_pipeline_for_latest_meeting(
            settings,
            send_telegram=body.send_telegram,
            mark_processed=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=safe_error_detail(exc, settings)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=safe_error_detail(exc, settings)) from exc

    return {
        "transcript_count": result.transcript_count,
        "idea_count": result.idea_count,
        "telegram_sent": result.telegram_sent,
        "analysis": result.analysis,
        "telegram_preview": result.telegram_preview,
    }


@router.get("/ideas/latest")
def latest_ideas():
    analysis = load_latest_analysis()
    if not analysis:
        raise HTTPException(status_code=404, detail="No analysis results yet.")
    return analysis
