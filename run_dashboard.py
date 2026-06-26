#!/usr/bin/env python3
"""Start the web dashboard, daily scheduler, and Telegram bot.

This is the primary entry point for local dev and Railway deploy.
Binds to the PORT environment variable (Railway sets this automatically).

Usage:
    python run_dashboard.py
    open http://localhost:8080
"""

import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run("src.api.app:app", host="0.0.0.0", port=port, reload=False)
