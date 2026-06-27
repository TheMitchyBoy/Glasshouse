"""FastAPI application entry point.

On startup (lifespan):
  - Starts the daily meeting scan scheduler
  - Starts Telegram bot long-polling for commands and Q&A

Serves the web dashboard at / and REST API at /api/*.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.routes import router
from src.api.security import SecurityHeadersMiddleware, get_cors_origins, require_api_key
from src.config import get_settings
from src.services.scheduler import start_daily_scheduler, stop_daily_scheduler
from src.services.telegram_bot import start_telegram_bot, stop_telegram_bot

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT / "frontend"


def _validate_security_settings() -> None:
    settings = get_settings()
    if settings.is_production and not settings.api_secret_key:
        raise RuntimeError("API_SECRET_KEY is required when ENV=production")


@asynccontextmanager
async def lifespan(_: FastAPI):
    _validate_security_settings()
    start_daily_scheduler()
    start_telegram_bot()
    yield
    stop_telegram_bot()
    stop_daily_scheduler()


settings = get_settings()
app = FastAPI(title="Glasshouse", version="1.0.0", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(settings),
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
)
app.include_router(router, prefix="/api", dependencies=[Depends(require_api_key)])

if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
