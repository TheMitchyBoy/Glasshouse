"""API security helpers: authentication, rate limiting, and safe error responses."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock
from time import time

from fastapi import Header, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from src.config import Settings, get_settings

_PUBLIC_PATHS = {"/api/health", "/api/auth/required"}

_rate_lock = Lock()
_rate_hits: dict[str, list[float]] = defaultdict(list)


def is_production(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return settings.is_production


def get_cors_origins(settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    if settings.cors_origins:
        return [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    if is_production(settings):
        return []
    return ["http://localhost:8000", "http://127.0.0.1:8000"]


def safe_error_detail(exc: Exception | str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    if is_production(settings):
        return "An internal error occurred."
    return str(exc)


def safe_status_error(exc: Exception | str | None, settings: Settings | None = None) -> str | None:
    if exc is None:
        return None
    settings = settings or get_settings()
    if is_production(settings):
        return "Unavailable"
    return str(exc)


def _extract_api_key(
    x_api_key: str | None,
    authorization: str | None,
) -> str | None:
    if x_api_key:
        return x_api_key
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    authorization: str | None = Header(None),
) -> None:
    settings = get_settings()
    if request.url.path in _PUBLIC_PATHS:
        return
    if not settings.api_secret_key:
        return

    token = _extract_api_key(x_api_key, authorization)
    if not token or token != settings.api_secret_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def check_rate_limit(
    request: Request,
    *,
    scope: str,
    limit: int,
    window_seconds: int = 60,
) -> None:
    client = request.client.host if request.client else "unknown"
    key = f"{scope}:{client}"
    now = time()

    with _rate_lock:
        hits = _rate_hits[key]
        hits[:] = [timestamp for timestamp in hits if now - timestamp < window_seconds]
        if len(hits) >= limit:
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
        hits.append(now)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if is_production():
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
