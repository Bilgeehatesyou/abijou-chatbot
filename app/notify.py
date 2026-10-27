"""Telegram alert to the team when someone books a meeting with Ajilt-AI.

Covers every way a meeting reaches us — the website form, the website chat,
Facebook and Instagram (direct or via n8n / ManyChat) — because they all end in
`BookingFlow._book` or `meetings.create`. Demo businesses' bookings are not sent.

Sent inline (Vercel has nothing running after the response), with a short
timeout, and never raises: a Telegram hiccup must not lose the booking.
"""
import logging
from datetime import datetime

import httpx

from .config import settings
from .crm import CHANNELS

TIMEOUT = 5
WEEKDAYS = ["Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба", "Ням"]


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


def meeting_text(*, channel: str, start: str, name: str, phone: str, what: str,
                 calendar_status: str = "booked", extra: tuple = ()) -> str:
    lines = [
        "📅 Шинэ уулзалт товлогдлоо",
        f"Суваг: {CHANNELS.get(channel, channel or '—')}",
        f"Хэзээ: {_when(start)}",
        f"Төрөл: {what}",
        f"Нэр: {name}",
        f"Утас: {phone}",
        *[line for line in extra if line],
    ]
    if calendar_status != "booked":
        lines.append("⚠️ Google Calendar-т орсонгүй — /meetings хуудсаас шалгана уу")
    return "\n".join(lines)


def meeting(**kw) -> bool:
    """Build and send the alert. Never raises."""
    if not configured():
        return False
    try:
        text = meeting_text(**kw)
    except Exception as e:
        print(f"[notify] could not build the alert: {type(e).__name__}: {e}")
        return False
    return send(text)
