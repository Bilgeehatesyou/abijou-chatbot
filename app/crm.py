"""Everything the chatbot hands to bas.mn (Perfex CRM), and what it reads back.

Outgoing — queued in `crm_outbox` next to the row it describes, sent right after
(by the background worker, or inline on serverless), retried with backoff:

  lead            sales-flow lead (leads row)          -> Lead
  booking         any chatbot booking (bookings row)   -> Lead + calendar event
  site_booking    ajiltai.tech form (site_bookings)    -> Lead + calendar event
  order           order / stay request (requests row)  -> Lead (+ custom table row)
  meeting_status  new/confirmed/done/cancelled in /meetings -> event title or deleted
  order_status    status change in /orders             -> a line on the lead

A Lead is found by phone number before one is created, so one person is one
lead however many times they write. Each event's description links to its lead,
because Perfex events have no lead field of their own.

Incoming — `pull()` every BASMN_PULL_SECONDS:

  calendar  mirrored into crm_events: meetings staff add in bas.mn block Ajilt-AI's
            booking slots; our meetings deleted there become cancelled here, and
            moved ones move (in Google Calendar too)
  items     STARTER / PRO / PREMIUM in bas.mn Items override config/pricing.yaml

Why polling and not webhooks: bas.mn's "Event Webhooks" fire on API traffic only
(request received, auth failed ...), never when staff edit a lead or an event.

Demo businesses are written too, so the tour can show a booking landing in a
real CRM, but marked: "[DEMO]" titles, grey events, a "demo" tag on the lead.

    python -m app.crm status        # what is queued, failed, last pull
    python -m app.crm check         # read-only test of the key and the ids in .env
    python -m app.crm flush         # send what is queued now
    python -m app.crm pull          # read bas.mn back now
    python -m app.crm retry         # put failed jobs back in the queue
    python -m app.crm fix-old-leads [--apply]   # relabel leads the old sync sent as Google/Customer
"""
import argparse
import json
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from .basmn import BasError, BasMN, configured
from .config import settings

AJILT_AI = "ajilt_ai"
DEMO_PREFIX = "[DEMO]"
DEMO_TAG = "demo"
COLORS = {"chatbot": "#16A34A", "website": "#F97316", "demo": "#9CA3AF"}
STATUS_MARKS = {"confirmed": "✅ ", "done": "☑ "}

MAX_ATTEMPTS = 12               # ~ a day of retries before a job is parked as failed
WORKER_IDLE_SECONDS = 30
INLINE_JOBS = 5                 # serverless: jobs sent before the response returns

CHANNELS = {"messenger": "Messenger", "instagram": "Instagram",
            "zevchat": "Messenger (ZevChat)", "web": "Вэбсайт чат", "website": "Вэбсайт маягт",
            "cli": "Туршилт"}


class NotReady(Exception):
    """A job depends on one that hasn't been sent yet; try again later."""


def _client() -> Optional[BasMN]:
    return BasMN() if configured() else None


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.BOOKING_TIMEZONE)


def _local(iso: str) -> datetime:
    """Our ISO time as the naive local time bas.mn stores."""
    dt = datetime.fromisoformat(iso)
    return (dt.astimezone(_tz()) if dt.tzinfo else dt).replace(tzinfo=None, second=0, microsecond=0)


def _crm_time(text: str) -> Optional[datetime]:
    try:
        return datetime.strptime((text or "")[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _note(lines: List[str]) -> str:
    return "\n".join(line for line in lines if line)


def source_for(channel: str) -> int:
    if channel in ("web", "website", "cli"):
        return settings.BASMN_SOURCE_WEBSITE
    if channel == "instagram" and settings.BASMN_SOURCE_INSTAGRAM:
        return settings.BASMN_SOURCE_INSTAGRAM
    return settings.BASMN_SOURCE_FACEBOOK


def lead_link(lead_id) -> str:
    return f"{settings.BASMN_URL}/admin/leads/index/{lead_id}" if lead_id else ""


# ---------- queueing ----------

_kick = threading.Event()


def enqueue(store, kind: str, ref_id, payload: Optional[dict] = None):
    """Record work for bas.mn. Never raises: losing the CRM copy must not lose the visitor."""
    if not configured():
        return
    try:
        store.crm_enqueue(kind, ref_id, payload)
    except Exception as e:
        print(f"[crm] could not queue {kind} {ref_id}: {type(e).__name__}: {e}")
        return
    if settings.SERVERLESS:
        flush(store, limit=INLINE_JOBS)     # nothing runs after the response there
    else:
        _kick.set()


def flush(store, limit: int = 50, bas: Optional[BasMN] = None) -> Dict[str, int]:
    bas = bas or _client()
    result = {"sent": 0, "retry": 0, "failed": 0}
    if not bas:
        return result
    try:
        jobs = store.crm_claim(limit)
    except Exception as e:
        print(f"[crm] queue read failed: {type(e).__name__}: {e}")
        return result
    for job in jobs:
        handler = HANDLERS.get(job["kind"])
        try:
            if not handler:
                raise ValueError(f"unknown job kind {job['kind']!r}")
            handler(store, bas, job["ref_id"], job["payload"])
        except NotReady as e:
            store.crm_retry(job["id"], f"waiting: {e}", 60)
            result["retry"] += 1
        except Exception as e:
            attempts = job["attempts"] + 1
            give_up = attempts >= MAX_ATTEMPTS or isinstance(e, (ValueError, KeyError))
            delay = min(30 * 2 ** job["attempts"], 3600)
            store.crm_retry(job["id"], f"{type(e).__name__}: {e}", delay, give_up)
            result["failed" if give_up else "retry"] += 1
            print(f"[crm] {job['kind']} {job['ref_id']} failed (try {attempts}): {e}")
        else:
            store.crm_finish(job["id"])
            result["sent"] += 1
    return result


# ---------- leads ----------

def _merge_description(old: str, block: str) -> str:
    old = re.sub(r"<br\s*/?>", "", old or "").strip()     # bas.mn stores newlines as <br />
    if block.strip() in old:            # a retry of something already written
        return old
    stamp = datetime.now(_tz()).strftime("%Y-%m-%d %H:%M")
    return f"{old}\n\n— {stamp} —\n{block}".strip() if old else block


NO_NAME = "Чатботын лид"


def upsert_lead(bas: BasMN, *, name: str, phone: str, note: str, channel: str = "",
                email: str = "", company: str = "", value=None, lang: str = "mn",
                tags: Optional[List[str]] = None, title: str = "") -> Optional[str]:
    """One person = one lead: found by phone and topped up, else created."""
    existing = bas.find_lead_by_phone(phone) if phone else None
    if existing:
        lead_id = str(existing.get("id"))
        fields = {"description": _merge_description(existing.get("description", ""), note)}
        if name and existing.get("name") in ("", None, NO_NAME):   # the name came after the number
            fields["name"] = name
        if company and not existing.get("company"):
            fields["company"] = company
        if email and not existing.get("email"):
            fields["email"] = email
        if value and not _number(existing.get("lead_value")):
            fields["lead_value"] = value
        bas.update_lead(lead_id, fields)
        return lead_id
    lead_id = bas.create_lead(
        name=name or NO_NAME, phone=phone, email=email, company=company, note=note,
        source=source_for(channel), status=settings.BASMN_STATUS_NEW,
        assigned=settings.BASMN_ASSIGNED, tags=",".join(t for t in (tags or []) if t),
        lead_value=value or None, title=title,
        default_language="english" if lang == "en" else "mongolian",
    )
    if not lead_id and phone:             # created, but their API sent no id back
        found = bas.find_lead_by_phone(phone)
        lead_id = str(found["id"]) if found else None
    return lead_id


def _number(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _tags(channel: str, demo: bool, business: str = "") -> List[str]:
    tags = ["chatbot", CHANNELS.get(channel, channel)]
    if demo:
        tags += [DEMO_TAG, business]
    return tags


def push_lead(store, bas: BasMN, ref_id, p: dict):
    """A sales-flow lead: a callback request, or the person behind a booked meeting."""
    row = store.get_row("leads", ref_id)
    if not row:
        return
    price = row.get("quote")
    value = int(price) if price and str(price).isdigit() else None
    note = _note([
        p.get("interest", ""),
        f"Байгууллага: {row['org_name']}" if row.get("org_name") else "",
        f"Төрөл: {row['business_type']}" if row.get("business_type") else "",
        f"Үйл ажиллагаа: {row['industry']}" if row.get("industry") else "",
        f"Ажилтан: {row['employees']}" if row.get("employees") is not None else "",
        f"Салбар: {row['branches']}" if row.get("branches") is not None else "",
        f"Багц: {row['tier']}" if row.get("tier") else "",
        f"Үнийн санал: {int(price):,}₮/сар" if value else
        ("Үнийн санал: тусгай" if price == "custom" else ""),
        f"Уулзалт: {_local(row['slot']):%Y-%m-%d %H:%M}" if row.get("slot") else "",
        f"Суваг: {CHANNELS.get(row['channel'], row['channel'] or '—')}",
        "Ажилт-AI чатботоор бүртгэгдсэн.",
    ])
    lead_id = upsert_lead(bas, name=row.get("contact_name") or "", phone=row.get("phone") or "",
                          note=note, channel=row.get("channel") or "",
                          company=row.get("org_name") or "", value=value,
                          lang=p.get("lang", "mn"), tags=_tags(row.get("channel") or "", False))
    if lead_id:
        store.set_crm_ids("leads", ref_id, crm_lead_id=lead_id)
        if row.get("path") == "booking" and settings.BASMN_STATUS_MEETING:
            bas.update_lead(lead_id, {"status": settings.BASMN_STATUS_MEETING})


# ---------- meetings ----------

def _event(bas: BasMN, *, title: str, start: datetime, end: datetime, description: str,
           color: str) -> Optional[str]:
    """Create the event unless a retry finds the first attempt already made it."""
    existing = bas.find_event(title, start)
    if existing:
        return existing
    return bas.create_event(title=title, start=start, end=end, staff_id=settings.BASMN_ASSIGNED,
                            description=description, color=color)


def push_booking(store, bas: BasMN, ref_id, p: dict):
    """A booking from the chatbot: Ajilt-AI's own meeting, or a demo business's."""
    row = store.get_row("bookings", ref_id)
    if not row:
        return
    demo = row["business_id"] != AJILT_AI
    business = p.get("business", row["business_id"])
    service = p.get("service", row.get("service_id") or "")
    channel = row.get("channel") or ""
    start, end = _local(row["start_at"]), _local(row["end_at"])
    details = [
        f"Үйлчилгээ: {service}" if service else "",
        f"Салбар: {p['branch']}" if p.get("branch") else "",
        f"Ажилтан: {p['staff']}" if p.get("staff") else "",
        f"Хаяг: {p['where']}" if p.get("where") else "",
        f"Цаг: {start:%Y-%m-%d %H:%M}–{end:%H:%M}",
        f"Үйлчлүүлэгч: {row['name']} · {row['phone']}",
        f"Бизнес: {business}" if demo else "",
        f"Суваг: {CHANNELS.get(channel, channel or '—')}",
        f"{DEMO_PREFIX} Ажилт-AI демо — жинхэнэ захиалга биш." if demo
        else "Ажилт-AI чатботоор захиалсан.",
    ]
    lead_id = row.get("crm_lead_id") or upsert_lead(
        bas, name=row["name"], phone=row["phone"], channel=channel, lang=p.get("lang", "mn"),
        note=_note([f"{DEMO_PREFIX} {business}: цаг захиалга" if demo else "Уулзалт товлосон",
                    *details]),
        tags=_tags(channel, demo, business))
    if lead_id:
        store.set_crm_ids("bookings", ref_id, crm_lead_id=lead_id)
    if row.get("crm_event_id"):
        return
    title = (f"{DEMO_PREFIX} {business}: {service} — {row['name']}" if demo
             else f"{service} — {row['name']}")
    event_id = _event(bas, title=title, start=start, end=end,
                      description=_note([*details, f"Лид: {lead_link(lead_id)}" if lead_id else ""]),
                      color=COLORS["demo" if demo else "chatbot"])
    if event_id:
        store.set_crm_ids("bookings", ref_id, crm_event_id=event_id)


def push_site_booking(store, bas: BasMN, ref_id, p: dict):
    """A meeting booked on the ajiltai.tech form."""
    from .meetings import FORMATS, PLATFORMS   # meetings imports nothing from here
    row = store.get_row("site_bookings", ref_id)
    if not row:
        return
    fmt = FORMATS.get(row["format"], {}).get("mn", row["format"])
    platform = PLATFORMS.get(row.get("platform") or "", "")
    start, end = _local(row["start_at"]), _local(row["end_at"])
    details = [
        f"Хэлбэр: {fmt}" + (f" ({platform})" if platform else ""),
        f"Цаг: {start:%Y-%m-%d %H:%M}–{end:%H:%M}",
        f"Нэр: {row['name']} · {row['phone']}",
        f"И-мэйл: {row['email']}" if row.get("email") else "",
        f"Бизнес: {row['business']}" if row.get("business") else "",
        f"Ажилчид: {row['employees']}" if row.get("employees") else "",
        f"Салбар: {row['branches']}" if row.get("branches") else "",
        f"Facebook: {row['facebook']}" if row.get("facebook") else "",
        f"Instagram: {row['instagram']}" if row.get("instagram") else "",
        f"Сонирхсон багц: {row['plan']}" if row.get("plan") else "",
        "Эх сурвалж: ajiltai.tech захиалгын маягт",
    ]
    lead_id = row.get("crm_lead_id") or upsert_lead(
        bas, name=row["name"], phone=row["phone"], email=row.get("email") or "",
        company=row.get("business") or "", channel="website", lang=row.get("lang") or "mn",
        note=_note(["Вэбсайтаас уулзалт товлосон", *details]), tags=_tags("website", False))
    if lead_id:
        store.set_crm_ids("site_bookings", ref_id, crm_lead_id=lead_id)
        if settings.BASMN_STATUS_MEETING:
            bas.update_lead(lead_id, {"status": settings.BASMN_STATUS_MEETING})
    if row.get("crm_event_id"):
        return
    event_id = _event(bas, title=f"{fmt} — {row['name']} (вэб)", start=start, end=end,
                      description=_note([*details, f"Лид: {lead_link(lead_id)}" if lead_id else ""]),
                      color=COLORS["website"])
    if event_id:
        store.set_crm_ids("site_bookings", ref_id, crm_event_id=event_id)


def _strip_marks(title: str) -> str:
    for mark in STATUS_MARKS.values():
        if title.startswith(mark):
            return title[len(mark):]
    return title


def push_meeting_status(store, bas: BasMN, ref_id, p: dict):
    """Confirm / done mark the event's title; cancelled deletes it; back to new
    (or confirmed after a cancel) puts it back."""
    table, status = p["table"], p["status"]
    create_kind = {"bookings": "booking", "site_bookings": "site_booking"}[table]
    row = store.get_row(table, ref_id)
    if not row:
        return
    if store.crm_has_pending(create_kind, ref_id):
        raise NotReady(f"{create_kind} {ref_id} not sent yet")

    event_id = row.get("crm_event_id")
    if status == "cancelled":
        if event_id:
            try:
                bas.delete_event(event_id)
            except BasError as e:
                if "not found" not in str(e).lower() and "no data" not in str(e).lower():
                    raise
            store.set_crm_ids(table, ref_id, crm_event_id="")
        if row.get("crm_lead_id"):
            fields = {"description": _merge_description(
                (bas.lead(row["crm_lead_id"]) or {}).get("description", ""),
                f"Уулзалт цуцлагдсан ({_local(row['start_at']):%Y-%m-%d %H:%M}).")}
            if settings.BASMN_STATUS_CANCELLED:
                fields["status"] = settings.BASMN_STATUS_CANCELLED
            bas.update_lead(row["crm_lead_id"], fields)
        return

    if not event_id:                     # re-opened after a cancel: create it again
        HANDLERS[create_kind](store, bas, ref_id, store.crm_first_payload(create_kind, ref_id))
        row = store.get_row(table, ref_id)
        event_id = row.get("crm_event_id")
        if not event_id:
            return
    current = bas.event(event_id)
    if not current:
        return
    title = STATUS_MARKS.get(status, "") + _strip_marks(current["title"])
    if title != current["title"]:
        bas.update_event(event_id, {"title": title}, current)
    if status == "confirmed" and row.get("crm_lead_id") and settings.BASMN_STATUS_MEETING:
        bas.update_lead(row["crm_lead_id"], {"status": settings.BASMN_STATUS_MEETING})


# ---------- orders ----------

ORDER_STATUS_MN = {"new": "шинэ", "confirmed": "баталгаажсан", "delivered": "хүргэгдсэн",
                   "cancelled": "цуцлагдсан"}


def push_order(store, bas: BasMN, ref_id, p: dict):
    row = store.get_row("requests", ref_id)
    if not row:
        return
    details = json.loads(row.get("details") or "[]")
    demo = p.get("demo", row["business_id"] != AJILT_AI)
    business = p.get("business", row["business_id"])
    title = row.get("title") or "Захиалга"
    channel = row.get("channel") or ""
    note = _note([
        f"{DEMO_PREFIX} {business}: {title}" if demo else title,
        "Захиалгын мэдээлэл:", *(f"• {d}" for d in details if d),
        f"Суваг: {CHANNELS.get(channel, channel or '—')}",
        f"Захиалгын дугаар: #{ref_id}",
    ])
    lead_id = row.get("crm_lead_id") or upsert_lead(
        bas, name=row["name"], phone=row["phone"], note=note, channel=channel,
        lang=p.get("lang", "mn"), tags=_tags(channel, demo, business))
    if lead_id:
        store.set_crm_ids("requests", ref_id, crm_lead_id=lead_id)
    if settings.BASMN_ORDERS_TABLE:
        bas.add_row(settings.BASMN_ORDERS_TABLE, {
            "order_ref": ref_id, "business": business, "title": title, "name": row["name"],
            "phone": row["phone"], "details": "\n".join(details), "status": row.get("status") or "new",
            "lead_id": lead_id or "", "channel": channel})


def push_order_status(store, bas: BasMN, ref_id, p: dict):
    if store.crm_has_pending("order", ref_id):
        raise NotReady(f"order {ref_id} not sent yet")
    row = store.get_row("requests", ref_id)
    if not row or not row.get("crm_lead_id"):
        return
    lead = bas.lead(row["crm_lead_id"]) or {}
    status = ORDER_STATUS_MN.get(p["status"], p["status"])
    bas.update_lead(row["crm_lead_id"], {"description": _merge_description(
        lead.get("description", ""), f"Захиалга #{ref_id}: {status}")})


HANDLERS: Dict[str, Callable] = {
    "lead": push_lead, "booking": push_booking, "site_booking": push_site_booking,
    "order": push_order, "meeting_status": push_meeting_status, "order_status": push_order_status,
}


# ---------- bas.mn -> bot ----------

def pull(store, bas: Optional[BasMN] = None, calendar=None) -> dict:
    """Read bas.mn back: calendar mirror, cancelled / moved meetings, price list."""
    bas = bas or _client()
    if not bas:
        return {}
    report = {"events": 0, "cancelled": 0, "moved": 0, "prices": 0}
    try:
        events = bas.events()
        store.replace_crm_events(events)
        report["events"] = len(events)
        by_id = {e["id"]: e for e in events}
        for m in store.crm_linked_meetings():
            if m["status"] == "cancelled":
                continue
            ev = by_id.get(str(m["crm_event_id"]))
            if ev is None:
                store.cancel_meeting(m["table"], m["id"])
                report["cancelled"] += 1
                continue
            start, end = _crm_time(ev["start"]), _crm_time(ev["end"])
            if not start or start == _local(m["start_at"]):
                continue
            if not end or end <= start:
                end = start + (_local(m["end_at"]) - _local(m["start_at"]))
            store.move_meeting(m["table"], m["id"], start.replace(tzinfo=_tz()).isoformat(),
                               end.replace(tzinfo=_tz()).isoformat())
            _move_google_event(store, calendar, m, start, end)
            report["moved"] += 1

        prices = {}
        for item in bas.items():
            words = (item.get("name") or "").strip().split()
            if words and _number(item.get("rate")):
                prices.setdefault(words[0].upper(), int(_number(item["rate"])))
        store.crm_state_set("prices", prices)
        report["prices"] = len(prices)
        store.crm_state_set("last_pull", {"at": time.time(), "error": None, **report})
    except Exception as e:
        store.crm_state_set("last_pull", {"at": time.time(), "error": f"{type(e).__name__}: {e}"})
        print(f"[crm] pull failed: {type(e).__name__}: {e}")
    return report


def _move_google_event(store, calendar, m: dict, start: datetime, end: datetime):
    """Keep Google Calendar (what the booking flow and dashboard read) in step."""
    if not calendar or m["table"] != "bookings":
        return
    row = store.get_row("bookings", m["id"]) or {}
    calendar_id = store.get_calendar_id(m["business_id"])
    if not (row.get("event_id") and calendar_id):
        return
    try:
        calendar.move_event(calendar_id, row["event_id"], start.replace(tzinfo=_tz()),
                            end.replace(tzinfo=_tz()))
    except Exception as e:
        print(f"[crm] google move failed for booking {m['id']}: {e}")


def busy(store, start: datetime, end: datetime) -> list:
    """bas.mn events in [start, end) as booking-flow busy tuples, demo ones left out."""
    out = []
    try:
        rows = store.crm_events()
    except Exception as e:
        print(f"[crm] busy read failed: {e}")
        return out
    for e in rows:
        if (e["title"] or "").startswith(DEMO_PREFIX):
            continue
        s = _crm_time(e["start_at"])
        f = _crm_time(e["end_at"]) or (s + timedelta(minutes=60) if s else None)
        if not s:
            continue
        s, f = s.replace(tzinfo=_tz()), f.replace(tzinfo=_tz())
        if s < end and f > start:
            out.append((s, f, ""))
    return out


def prices(store) -> dict:
    """Tier -> monthly price from bas.mn Items, empty when there are none."""
    if not configured():
        return {}
    try:
        return store.crm_state_get("prices", {}) or {}
    except Exception:
        return {}


# ---------- background worker (servers; serverless uses inline flush + /api/basmn/sync) ----------

class CrmWorker:
    def __init__(self, store, calendar=None):
        self.store, self.calendar = store, calendar
        self._stop = threading.Event()
        self._last_pull = 0.0

    def start(self):
        if configured():
            threading.Thread(target=self._run, daemon=True, name="crm-sync").start()

    def stop(self):
        self._stop.set()
        _kick.set()

    def _run(self):
        while not self._stop.is_set():
            _kick.clear()
            try:
                while flush(self.store)["sent"]:     # keep going while there is work
                    pass
                if time.time() - self._last_pull >= settings.BASMN_PULL_SECONDS:
                    self._last_pull = time.time()
                    pull(self.store, calendar=self.calendar)
            except Exception as e:
                print(f"[crm] worker: {type(e).__name__}: {e}")
            _kick.wait(WORKER_IDLE_SECONDS)


def status(store) -> dict:
    return {
        "configured": configured(),
        "url": settings.BASMN_URL,
        "queue": store.crm_counts(),
        "last_pull": store.crm_state_get("last_pull"),
        "prices": store.crm_state_get("prices", {}),
        "failed": [{k: j[k] for k in ("id", "kind", "ref_id", "attempts", "last_error")}
                   for j in store.crm_jobs("failed", 20)],
        "waiting": [{k: j[k] for k in ("id", "kind", "ref_id", "attempts", "last_error")}
                    for j in store.crm_jobs("pending", 20) if j["attempts"]],
    }


# ---------- one-off repair ----------

OLD_MARKERS = ("Ажилт-AI чатботоор", "Ажилт-AI демо")
OLD_CHANNELS = {**{v: k for k, v in CHANNELS.items()}, "Вэбсайт": "web"}   # first version's label


def fix_old_leads(bas: BasMN, apply: bool = False) -> List[str]:
    """Leads the first version of this sync wrote with source 1 / status 1, which in
    aibiz.bas.mn mean "Google" / "Customer". Only leads whose description says the
    chatbot made them are touched; the channel comes from their "Суваг:" line."""
    lines = []
    for lead in bas.leads():
        desc = lead.get("description") or ""
        if not any(m in desc for m in OLD_MARKERS):
            continue
        m = re.search(r"Суваг:\s*([^\n]+)", desc)
        channel = OLD_CHANNELS.get(m.group(1).strip(), "") if m else ""
        want = {"source": source_for(channel), "status": settings.BASMN_STATUS_NEW}
        have = {k: int(_number(lead.get(k))) for k in want}
        if have == want:
            continue
        lines.append(f"lead {lead.get('id')} {lead.get('name')!r}: source {have['source']}->"
                     f"{want['source']}, status {have['status']}->{want['status']}")
        if apply:
            bas.update_lead(str(lead["id"]), want)
    lines.append(f"{len(lines)} lead(s) " + ("fixed" if apply else "to fix — run again with --apply"))
    return lines


# ---------- command line ----------

def check(bas: BasMN) -> List[str]:
    """Read-only: does the key work, and do the ids in .env exist?"""
    lines = []
    staff = bas.staff()
    lines.append(f"✓ API key works — {len(staff)} staff: "
                 + ", ".join(f"{s['id']}={s['name']}" for s in staff))
    if settings.BASMN_ASSIGNED and str(settings.BASMN_ASSIGNED) not in {s["id"] for s in staff}:
        lines.append(f"✗ BASMN_ASSIGNED={settings.BASMN_ASSIGNED} is not a staff id")
    lines.append(f"✓ calendar readable — {len(bas.events())} events")
    items = bas.items()
    lines.append(f"✓ items readable — {len(items)} items"
                 + ("" if items else " (add STARTER / PRO / PREMIUM to manage prices in bas.mn)"))
    lines.append(f"• new leads get status {settings.BASMN_STATUS_NEW}, sources "
                 f"facebook={settings.BASMN_SOURCE_FACEBOOK} "
                 f"instagram={settings.BASMN_SOURCE_INSTAGRAM or settings.BASMN_SOURCE_FACEBOOK} "
                 f"website={settings.BASMN_SOURCE_WEBSITE}, owner {settings.BASMN_ASSIGNED}")
    lines.append("  (status/source names aren't in their API: compare with bas.mn > Setup > Leads)")
    return lines


def main():
    from .store import Store
    parser = argparse.ArgumentParser(prog="python -m app.crm")
    parser.add_argument("command", choices=["status", "check", "flush", "pull", "retry",
                                            "fix-old-leads"])
    parser.add_argument("--apply", action="store_true", help="fix-old-leads: really change them")
    args = parser.parse_args()
    if args.command != "status" and not configured():
        raise SystemExit("set BASMN_URL and BASMN_API_KEY in .env first")
    store = Store(settings.DB_PATH)
    if args.command == "status":
        print(json.dumps(status(store), ensure_ascii=False, indent=2, default=str))
    elif args.command == "check":
        print("\n".join(check(BasMN())))
    elif args.command == "flush":
        total = {"sent": 0, "retry": 0, "failed": 0}
        while True:
            r = flush(store)
            for k in total:
                total[k] += r[k]
            if not r["sent"]:
                break
        print(total)
    elif args.command == "pull":
        from .gcal import get_calendar
        print(pull(store, calendar=get_calendar()))
    elif args.command == "retry":
        print(f"{store.crm_requeue_failed()} failed jobs queued again")
    elif args.command == "fix-old-leads":
        print("\n".join(fix_old_leads(BasMN(), apply=args.apply)))


if __name__ == "__main__":
    main()
