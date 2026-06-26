"""Telegram bot: long-polling for commands and conversational Q&A.

Routes messages from TELEGRAM_CHAT_ID only (security).
  /latest, /ideas  → full structured video-ideas pipeline
  /reset           → clear agent conversation memory
  anything else    → meeting_agent.answer_question()
"""

from __future__ import annotations

import logging
import re
import threading
import time

import httpx

from src.config import Settings, get_settings
from src.notifications.telegram import send_telegram_message
from src.services.meeting_agent import answer_question, clear_conversation
from src.services.pipeline import run_pipeline_for_latest_meeting

logger = logging.getLogger(__name__)

GENERATE_PATTERN = re.compile(
    r"(^/(latest|ideas|analyze|generate|brief|summary)\b)|"
    r"(\b(generate|analyze|summarize|summary|ideas|brief|video ideas)\b.*\b(meeting|transcript|latest)\b)|"
    r"(\b(latest|new)\b.*\b(meeting|transcript)\b)",
    re.IGNORECASE,
)

HELP_TEXT = (
    "<b>Meeting Video Ideas Bot</b>\n\n"
    "<b>Commands</b>\n"
    "/latest — analyze the latest meeting and send video ideas\n"
    "/ideas — same as /latest\n"
    "/reset — clear conversation memory\n"
    "/status — check bot status\n"
    "/help — show this message\n\n"
    "<b>Ask me anything</b>\n"
    "I use the latest meeting transcripts as context. Examples:\n"
    "• What was the most controversial vote?\n"
    "• Summarize the school board budget discussion\n"
    "• Give me 3 video angles on the housing item"
)

_bot_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _authorized_chat(settings: Settings, chat_id: int | str) -> bool:
    if not settings.telegram_chat_id:
        return False
    return str(chat_id) == str(settings.telegram_chat_id)


def _get_updates(bot_token: str, offset: int | None = None) -> list[dict]:
    params: dict = {"timeout": 30}
    if offset is not None:
        params["offset"] = offset

    response = httpx.get(
        f"https://api.telegram.org/bot{bot_token}/getUpdates",
        params=params,
        timeout=40.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description", "getUpdates failed"))
    return payload.get("result", [])


def _send_agent_reply(settings: Settings, chat_id: str, text: str) -> None:
    try:
        send_telegram_message(settings.telegram_bot_token, chat_id, text)
    except httpx.HTTPStatusError:
        # Fallback to plain text if HTML parsing fails
        plain = re.sub(r"<[^>]+>", "", text)
        send_telegram_message(
            settings.telegram_bot_token,
            chat_id,
            plain,
            parse_mode=None,
        )


def _handle_message(settings: Settings, message: dict) -> None:
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()

    if not text or chat_id is None:
        return

    chat_id_str = str(chat_id)
    if not _authorized_chat(settings, chat_id):
        logger.info("Ignored Telegram message from unauthorized chat %s", chat_id)
        return

    lowered = text.lower()
    if lowered.startswith("/help") or lowered == "/start":
        send_telegram_message(settings.telegram_bot_token, chat_id_str, HELP_TEXT)
        return

    if lowered.startswith("/reset"):
        clear_conversation(chat_id_str)
        send_telegram_message(
            settings.telegram_bot_token,
            chat_id_str,
            "<b>Conversation cleared.</b> Ask me a new question anytime.",
        )
        return

    if lowered.startswith("/status"):
        send_telegram_message(
            settings.telegram_bot_token,
            chat_id_str,
            "<b>Bot is running.</b>\nAsk a question about the latest meeting, or send /latest for full video ideas.",
        )
        return

    if lowered.startswith("/latest") or lowered.startswith("/ideas") or GENERATE_PATTERN.search(text):
        send_telegram_message(
            settings.telegram_bot_token,
            chat_id_str,
            "<i>Analyzing the latest meeting transcript…</i>",
        )
        try:
            result = run_pipeline_for_latest_meeting(settings, send_telegram=False)
            send_telegram_message(
                settings.telegram_bot_token,
                chat_id_str,
                result.telegram_preview,
            )
        except Exception as exc:
            logger.exception("Telegram on-demand analysis failed")
            send_telegram_message(
                settings.telegram_bot_token,
                chat_id_str,
                f"<b>Analysis failed:</b> {_escape(str(exc))}",
            )
        return

    try:
        reply = answer_question(text, chat_id_str, settings)
        _send_agent_reply(settings, chat_id_str, reply)
    except Exception as exc:
        logger.exception("Telegram agent reply failed")
        send_telegram_message(
            settings.telegram_bot_token,
            chat_id_str,
            f"<b>Sorry, I could not answer that:</b> {_escape(str(exc))}",
        )


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _poll_loop(settings: Settings) -> None:
    logger.info("Telegram bot polling started")
    offset: int | None = None

    while not _stop_event.is_set():
        try:
            updates = _get_updates(settings.telegram_bot_token, offset)
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message") or update.get("edited_message")
                if message:
                    _handle_message(settings, message)
        except Exception:
            logger.exception("Telegram polling error")
            time.sleep(5)

    logger.info("Telegram bot polling stopped")


def start_telegram_bot(settings: Settings | None = None) -> None:
    global _bot_thread
    settings = settings or get_settings()

    if not settings.telegram_polling_enabled:
        logger.info("Telegram polling disabled")
        return
    if not settings.telegram_configured:
        logger.info("Telegram polling skipped: not configured")
        return
    if _bot_thread and _bot_thread.is_alive():
        return

    _stop_event.clear()
    _bot_thread = threading.Thread(
        target=_poll_loop,
        args=(settings,),
        name="telegram-bot",
        daemon=True,
    )
    _bot_thread.start()


def stop_telegram_bot() -> None:
    _stop_event.set()
