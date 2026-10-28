"""Telegram alert to the clinic's coordinators for every booking made in the chat
(Instagram, Facebook, website).

Sent inline (Vercel has nothing running after the response), with a short
timeout, and never raises: a Telegram hiccup must not lose the booking.
"""
import logging
from datetime import datetime

import httpx

from .config import settings

TIMEOUT = 5
WEEKDAYS = ["Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба", "Ням"]
CHANNELS = {"messenger": "Facebook", "instagram": "Instagram", "web": "Вэб чат",
            "n8n": "n8n", "cli": "Туршилт (CLI)"}
LANGS = {"mn": "монгол", "en": "англи", "ko": "солонгос"}


class _HideToken(logging.Filter):
    """httpx logs every request URL, and Telegram's has the bot token in it."""

    def filter(self, record):
        token = settings.TELEGRAM_BOT_TOKEN
        if token and isinstance(record.args, tuple):
            record.args = tuple(str(a).replace(token, "***") if token in str(a) else a
                                for a in record.args)
        return True


logging.getLogger("httpx").addFilter(_HideToken())


def configured() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)


def send(text: str) -> bool:
    if not configured():
        return False
    try:
        r = httpx.post(f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                       json={"chat_id": settings.TELEGRAM_CHAT_ID, "text": text,
                             "disable_web_page_preview": True},
                       timeout=TIMEOUT)
        if r.status_code != 200:
            print(f"[notify] telegram answered {r.status_code}: {r.text[:200]}")
            return False
        return True
    except Exception as e:
        print(f"[notify] telegram failed: {type(e).__name__}: {e}")
        return False


def _when(start_iso: str) -> str:
    start = datetime.fromisoformat(start_iso)
    return f"{start:%Y-%m-%d} ({WEEKDAYS[start.weekday()]}) {start:%H:%M}"


def booking_text(row: dict, *, service_name: str, branch_name: str, price: str) -> str:
    lines = [
        "📅 Шинэ цаг захиалга",
        f"Салбар: {branch_name}",
        f"Хэзээ: {_when(row['start_at'])}",
        f"Эмчилгээ: {service_name}",
        f"Үнэ: {price}",
        f"Нэр: {row['name']}",
        f"Утас: {row['phone']}",
        f"Суваг: {CHANNELS.get(row['channel'], row['channel'] or '—')}, "
        f"хэл: {LANGS.get(row['lang'], row['lang'])}",
    ]
    if row.get("calendar_status") == "calendar_failed":
        lines.append("⚠️ Google Calendar-т орсонгүй — /bookings хуудсаас шалгана уу")
    return "\n".join(lines)


def booking(row: dict, **kw) -> bool:
    """Build and send the alert. Never raises."""
    if not configured():
        return False
    try:
        text = booking_text(row, **kw)
    except Exception as e:
        print(f"[notify] could not build the alert: {type(e).__name__}: {e}")
        return False
    return send(text)
