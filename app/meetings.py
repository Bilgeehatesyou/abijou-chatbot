"""Ajilt-AI's own sales meetings.

Two ways a prospect books us:
  - the chatbot's sales flow  -> `bookings` (business_id = 'ajilt_ai') + Google Calendar
  - the ajiltai.tech form     -> `site_bookings` + the same Google Calendar

This module takes the website's POST (sent by send-booking.php), validates it
again on our side, writes the calendar event and stores the row. The /meetings
page then shows both sources in one list.
"""
import re
from datetime import datetime, timedelta

from . import crm
from .booking import local_tz, normalize_phone
from .store import AJILT_AI, Store

# The three formats the website form offers, with the duration it promises.
FORMATS = {
    "online": {"minutes": 45, "mn": "Онлайн уулзалт", "en": "Online meeting"},
    "office": {"minutes": 60, "mn": "Биечлэн уулзах", "en": "In-person meeting"},
    "social": {"minutes": 20, "mn": "Чатаар (Facebook / Instagram)", "en": "Chat (Facebook / Instagram)"},
}
PLATFORMS = {"fb": "Facebook", "ig": "Instagram", "": ""}
# Tangerine, so website meetings stand out from the chatbot's in Google Calendar too.
WEBSITE_COLOR_ID = "6"
MAX_PAST_HOURS = 2      # allow a little clock skew, reject anything older
MAX_AHEAD_DAYS = 120


class BadBooking(ValueError):
    """The payload didn't pass our own checks (never trust the sender)."""


def _text(v, limit: int = 200) -> str:
    s = re.sub(r"\s+", " ", str(v or "").replace("\x00", " ")).strip()
    return s[:limit]


def parse(data: dict) -> dict:
    """Validate the website payload and turn it into a site_bookings row."""
    fmt = _text(data.get("type"), 20)
    if fmt not in FORMATS:
        raise BadBooking("unknown meeting format")

    date, time_s = _text(data.get("date"), 10), _text(data.get("time"), 5)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not re.fullmatch(r"\d{2}:\d{2}", time_s):
        raise BadBooking("bad date or time")
    try:
        start = datetime.fromisoformat(f"{date}T{time_s}").replace(tzinfo=local_tz())
    except ValueError:
        raise BadBooking("bad date or time")

    now = datetime.now(local_tz())
    if start < now - timedelta(hours=MAX_PAST_HOURS):
        raise BadBooking("meeting is in the past")
    if start > now + timedelta(days=MAX_AHEAD_DAYS):
        raise BadBooking("meeting is too far ahead")

    name = _text(data.get("name"), 120)
    phone = normalize_phone(_text(data.get("phone"), 40))
    if not name:
        raise BadBooking("name is required")
    if not phone:
        raise BadBooking("phone must be 8 digits")

    minutes = FORMATS[fmt]["minutes"]
    try:
        sent = int(data.get("duration") or 0)
        if 5 <= sent <= 480:
            minutes = sent
    except (TypeError, ValueError):
        pass

    platform = _text(data.get("platform"), 20)
    return {
        "format": fmt,
        "platform": platform if platform in PLATFORMS else "",
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(minutes=minutes)).isoformat(),
        "duration": minutes,
        "name": name,
        "phone": phone,
        "email": _text(data.get("email"), 160),
        "employees": _text(data.get("employees"), 10),
        "branches": _text(data.get("branches"), 10),
        "business": _text(data.get("business"), 80),
        "facebook": _text(data.get("facebook"), 200),
        "instagram": _text(data.get("instagram"), 120),
        "plan": _text(data.get("plan"), 20),
        "lang": "en" if data.get("lang") == "en" else "mn",
    }


def event_body(row: dict) -> tuple:
    """Summary + description for the Google Calendar event."""
    fmt = FORMATS[row["format"]]
    platform = PLATFORMS.get(row["platform"], "")
    summary = f"{fmt['mn']} — {row['name']} (вэб)"
    lines = [
        f"Хэлбэр: {fmt['mn']}" + (f" ({platform})" if platform else ""),
        f"Нэр: {row['name']}",
        f"Утас: {row['phone']}",
        f"И-мэйл: {row['email'] or '—'}",
        f"Ажилчид: {row['employees'] or '—'}",
        f"Салбар: {row['branches'] or '—'}",
        f"Бизнес: {row['business'] or '—'}",
        f"Facebook: {row['facebook'] or '—'}",
        f"Instagram: {row['instagram'] or '—'}",
        f"Сонирхсон багц: {row['plan'] or '—'}",
        "",
        "Эх сурвалж: ajiltai.tech захиалгын маягт",
    ]
    return summary, "\n".join(lines)


def create(store: Store, calendar, data: dict) -> dict:
    """Validate, put it in the Ajilt-AI calendar, store it. Raises BadBooking."""
    row = parse(data)
    row["event_id"], row["calendar_status"] = None, "no_calendar"

    calendar_id = store.get_calendar_id(AJILT_AI)
    if calendar and calendar_id:
        summary, description = event_body(row)
        try:
            event = calendar.create_event(
                calendar_id, summary, description,
                datetime.fromisoformat(row["start_at"]), datetime.fromisoformat(row["end_at"]),
                private={"source": "website", "name": row["name"], "phone": row["phone"]},
                color_id=WEBSITE_COLOR_ID,
            )
            row["event_id"], row["calendar_status"] = event.get("id"), "booked"
        except Exception as e:   # the meeting is still saved; the page shows the warning
            print(f"[meetings] calendar insert failed: {e}")
            row["calendar_status"] = "calendar_failed"

    row["id"] = store.save_site_booking(row)
    crm.enqueue(store, "site_booking", row["id"])
    return row


def mark_clashes(meetings: list) -> list:
    """Flag meetings whose times overlap another one, so a website booking that
    lands on top of a chatbot booking is visible instead of silent."""
    live = [m for m in meetings if m["status"] != "cancelled" and m["start_at"] and m["end_at"]]
    live.sort(key=lambda m: m["start_at"])
    for m in meetings:
        m["clash"] = False
    for a, b in zip(live, live[1:]):
        if b["start_at"] < a["end_at"]:
            a["clash"] = b["clash"] = True
    return meetings


def payload(store: Store) -> dict:
    meetings = mark_clashes(store.list_meetings())
    for m in meetings:
        m["format_label"] = FORMATS.get(m["format"], {}).get("mn", "") if m["format"] else ""
        m["platform_label"] = PLATFORMS.get(m["platform"], "")
    return {"meetings": meetings, "now": datetime.now(local_tz()).isoformat(),
            "calendar": bool(store.get_calendar_id(AJILT_AI))}
