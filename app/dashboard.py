"""Owner dashboard: mirrors each business's Google Calendar into SQLite and
serves it to the web UI in app/static/.

    python -m app.dashboard sync                  # pull every linked calendar once
    python -m app.dashboard seed --only salon     # fill a calendar with ~3 months of fake bookings
    python -m app.dashboard seed --only salon --clear   # remove the fake bookings again

The calendar is the source of truth: chatbot bookings, events the owner adds by
hand, and deletions (= cancellations) all show up after the next sync. The
server re-syncs every SYNC_SECONDS in a background thread.
"""
import argparse
import random
import re
import threading
import time as _time
from datetime import datetime, time, timedelta
from typing import Optional

from .booking import STAFF_EVENT_COLORS, local_tz, normalize_phone, opening_hours
from .config import settings
from .demo_data import load_seeds
from .gcal import GoogleCalendar, event_times, get_calendar
from .store import Store

SYNC_SECONDS = 60
SYNC_PAST_DAYS = 240
SYNC_FUTURE_DAYS = 90


def booking_configs() -> dict:
    """Seed entries of every business that takes bookings, keyed by id."""
    return {b["id"]: b for b in load_seeds()["businesses"] if "booking" in b}


# ---------- calendar event -> row ----------

def _find_by_name(options: list, text: str) -> Optional[str]:
    low = (text or "").strip().lower()
    for o in options:
        if any(n.lower() == low for n in o["name"].values()):
            return o["id"]
    return None


def parse_event(ev: dict, cfg: dict) -> dict:
    """Chatbot events carry everything in private properties; events typed in by
    hand only have a title/description, so fall back to reading those."""
    tz = local_tz()
    private = ev.get("extendedProperties", {}).get("private", {})
    desc = ev.get("description", "") or ""
    summary = ev.get("summary", "") or ""

    def line(label):
        m = re.search(rf"{label}:\s*(.+)", desc)
        return m.group(1).strip() if m else ""

    service = private.get("service") or _find_by_name(cfg["services"], line("Үйлчилгээ"))
    if not service:  # "Haircut — Bold" style titles
        service = _find_by_name(cfg["services"], summary.split(" — ")[0])
    staff = private.get("staff") or _find_by_name(cfg.get("staff", []), line("Ажилтан"))
    if not staff and "(" in summary:  # "Pedicure — Saraa (Undram)"
        staff = _find_by_name(cfg.get("staff", []), summary.rsplit("(", 1)[1].rstrip(") "))
    name = private.get("name") or (summary.split(" — ", 1)[1].split(" (")[0]
                                   if " — " in summary else summary)
    phone = private.get("phone") or normalize_phone(line("Утас")) or ""
    cancelled = ev.get("status") == "cancelled" or private.get("status") == "cancelled"
    start, end = event_times(ev, tz)
    source = private.get("channel") or ("chatbot" if private.get("source") == "ajilt-demo"
                                        else "manual")
    return {
        "event_id": ev["id"],
        "status": "cancelled" if cancelled else "booked",
        "start_at": start.astimezone(tz).replace(tzinfo=None).isoformat(timespec="minutes"),
        "end_at": end.astimezone(tz).replace(tzinfo=None).isoformat(timespec="minutes"),
        "summary": summary,
        "service_id": service or "",
        "staff_id": staff or "",
        "branch_id": private.get("branch", ""),
        "name": name.strip(),
        "phone": phone,
        "sender_id": private.get("sender", ""),
        "source": source,
        "created_at": ev.get("created", ""),
        "updated_at": ev.get("updated", ""),
    }


def sync_business(store: Store, cal: GoogleCalendar, business_id: str, cfg: dict) -> int:
    calendar_id = store.get_calendar_id(business_id)
    if not calendar_id:
        return 0
    now = datetime.now(local_tz())
    since = datetime.combine(now.date() - timedelta(days=SYNC_PAST_DAYS), time.min, local_tz())
    until = datetime.combine(now.date() + timedelta(days=SYNC_FUTURE_DAYS), time.min, local_tz())
    try:
        events = cal.events(calendar_id, since, until, show_deleted=True)
    except Exception as e:
        store.set_sync_error(business_id, str(e)[:300])
        raise
    # all-day events are days off / holidays: they block the chatbot but aren't bookings
    rows = [parse_event(ev, cfg["booking"]) for ev in events if "dateTime" in ev.get("start", {})]
    store.replace_calendar_events(business_id, rows,
                                  since.replace(tzinfo=None).isoformat(timespec="minutes"),
                                  until.replace(tzinfo=None).isoformat(timespec="minutes"))
    return len(rows)


def sync_all(store: Store, cal: GoogleCalendar):
    for business_id, cfg in booking_configs().items():
        try:
            sync_business(store, cal, business_id, cfg)
        except Exception as e:
            print(f"[dashboard] sync failed for {business_id}: {e}")


class SyncWorker:
    def __init__(self, store: Store, cal: Optional[GoogleCalendar]):
        self.store, self.cal = store, cal
        self._stop = threading.Event()

    def start(self):
        if self.cal:
            threading.Thread(target=self._run, daemon=True, name="calendar-sync").start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            sync_all(self.store, self.cal)
            self._stop.wait(SYNC_SECONDS)


# ---------- API payload ----------

def customer_key(row: dict) -> str:
    if row["phone"]:
        return "p:" + row["phone"]
    if row["sender_id"]:
        return "s:" + row["sender_id"]
    if row["name"]:
        return "n:" + row["name"].lower()
    return "e:" + row["event_id"]


def dashboard_payload(store: Store, business_id: str) -> Optional[dict]:
    seed = booking_configs().get(business_id)
    if not seed:
        return None
    cfg = seed["booking"]
    rows = store.calendar_events(business_id)

    # visit number per customer: 1 = first-time, 2+ = regular
    seen: dict = {}
    for r in rows:  # already sorted by start
        key = customer_key(r)
        r["customer"] = key
        prior = seen.get(key, 0)
        r["visit"] = prior + 1
        r["customer_type"] = "new" if prior == 0 else "regular"
        if r["status"] != "cancelled":
            seen[key] = prior + 1
        r.pop("summary", None)
        r.pop("sender_id", None)

    staff = [{**p, "color": i % len(STAFF_EVENT_COLORS)} for i, p in enumerate(cfg.get("staff", []))]
    return {
        "business": {
            "id": business_id, "industry": seed["industry"], "emoji": seed["emoji"],
            "name": seed["name"], "kind": seed["kind"],
        },
        "hours": cfg["hours"],
        "services": cfg["services"],
        "staff": staff,
        "branches": [{"id": b["id"], "name": b["name"]} for b in cfg.get("branches", [])],
        "events": rows,
        "now": datetime.now(local_tz()).replace(tzinfo=None).isoformat(timespec="minutes"),
        "calendar_linked": bool(store.get_calendar_id(business_id)),
        "sync": store.get_sync_state(business_id),
    }


def business_list(store: Store) -> list:
    out = []
    for business_id, seed in booking_configs().items():
        out.append({"id": business_id, "industry": seed["industry"], "emoji": seed["emoji"],
                    "name": seed["name"], "kind": seed["kind"],
                    "calendar_linked": bool(store.get_calendar_id(business_id))})
    return out


# ---------- fake history for demos ----------

FIRST_NAMES = [
    "Анударь", "Батцэцэг", "Болормаа", "Мөнхзаяа", "Номиндарь", "Оюунбилэг", "Саруул", "Солонго",
    "Туяа", "Хонгорзул", "Энхжаргал", "Сэлэнгэ", "Уянга", "Маралмаа", "Гэрэлмаа", "Цэцэгмаа",
    "Нандин", "Ариунаа", "Эрдэнэчимэг", "Хулангоо", "Бат-Эрдэнэ", "Ганбаатар", "Тэмүүлэн", "Билгүүн",
    "Мөнх-Очир", "Эрхэмбаяр", "Төгөлдөр", "Анхбаяр", "Сүхбат", "Амарсайхан", "Жавхлан", "Дөлгөөн",
    "Хүслэн", "Мишээл", "Ану", "Золбоо", "Индра", "Одгэрэл", "Пүрэвсүрэн", "Энх-Амгалан",
]

# per-business shape of the fake history
SEED_PROFILES = {
    "salon": {"days_back": 100, "days_ahead": 21, "per_staff_day": (1.0, 2.8), "new_share": 0.3},
    "dental": {"days_back": 120, "days_ahead": 21, "per_staff_day": (0.8, 2.0), "new_share": 0.35},
    "education": {"days_back": 120, "days_ahead": 14, "per_staff_day": (0.3, 1.2), "new_share": 0.8},
}
DEFAULT_PROFILE = {"days_back": 120, "days_ahead": 14, "per_staff_day": (1.0, 2.5), "new_share": 0.4}
CANCEL_RATE = 0.08
CHATBOT_SHARE = 0.65


class _Customers:
    def __init__(self, rng: random.Random, new_share: float):
        self.rng, self.new_share = rng, new_share
        self.people: list = []  # (name, phone, loyalty weight)

    def pick(self) -> tuple:
        if not self.people or self.rng.random() < self.new_share:
            phone = str(self.rng.choice([8, 9])) + "".join(str(self.rng.randint(0, 9)) for _ in range(7))
            loyalty = self.rng.choice([1, 1, 1, 2, 4, 8])
            person = (self.rng.choice(FIRST_NAMES), phone, loyalty)
            self.people.append(person)
            return person
        return self.rng.choices(self.people, weights=[p[2] for p in self.people])[0]


def fake_events(business_id: str, seed: dict, rng: random.Random) -> list:
    cfg = seed["booking"]
    profile = SEED_PROFILES.get(business_id) or SEED_PROFILES.get(seed["industry"], DEFAULT_PROFILE)
    services = {s["id"]: s for s in cfg["services"]}
    staff = cfg.get("staff") or [{"id": "", "services": list(services)}]
    customers = _Customers(rng, profile["new_share"])
    tz = local_tz()
    today = datetime.now(tz).date()
    lo, hi = profile["per_staff_day"]
    bodies = []
    for offset in range(-profile["days_back"], profile["days_ahead"] + 1):
        day = today + timedelta(days=offset)
        window = opening_hours(cfg["hours"], day)
        if not window:
            continue
        # business grows over time; weekends busier; future is only partly booked
        growth = 0.6 + 0.4 * (offset + profile["days_back"]) / profile["days_back"]
        weekend = 1.3 if day.weekday() >= 5 else 1.0
        future = 1.0 if offset <= 0 else max(0.15, 0.8 - offset * 0.04)
        for person in staff:
            target = rng.uniform(lo, hi) * growth * weekend * future
            count = int(target) + (rng.random() < target % 1)
            t = window[0] + timedelta(minutes=30 * rng.randint(0, 3))
            for _ in range(count):
                service = services[rng.choice(person.get("services") or list(services))]
                t += timedelta(minutes=30 * rng.randint(0, 4))
                end = t + timedelta(minutes=service["minutes"])
                if end > window[1]:
                    break
                bodies.append(_fake_body(cfg, person, service, t, end, customers.pick(), rng))
                t = end
    return bodies


def _fake_body(cfg, person, service, start, end, customer, rng) -> dict:
    name, phone, _ = customer
    staff_cfg = next((p for p in cfg.get("staff", []) if p["id"] == person["id"]), None)
    cancelled = rng.random() < CANCEL_RATE
    channel = "chatbot" if rng.random() < CHATBOT_SHARE else rng.choice(["phone", "walk-in"])
    title = f"{service['name']['mn']} — {name}" + (f" ({staff_cfg['name']['mn']})" if staff_cfg else "")
    body = {
        "summary": ("❌ " if cancelled else "") + title,
        "description": (f"Утас: {phone}\nҮйлчилгээ: {service['name']['mn']}\n"
                        + (f"Ажилтан: {staff_cfg['name']['mn']}\n" if staff_cfg else "")
                        + "Туршилтын өгөгдөл (Ajilt-AI демо)"),
        "start": {"dateTime": start.isoformat(), "timeZone": settings.BOOKING_TIMEZONE},
        "end": {"dateTime": end.isoformat(), "timeZone": settings.BOOKING_TIMEZONE},
        "extendedProperties": {"private": {
            "source": "seed", "channel": channel, "service": service["id"],
            "staff": person["id"], "branch": person.get("branch", ""), "name": name, "phone": phone,
            **({"status": "cancelled"} if cancelled else {}),
        }},
    }
    if cancelled:
        body["transparency"] = "transparent"  # doesn't block the slot for the chatbot
    if staff_cfg:
        body["colorId"] = STAFF_EVENT_COLORS[cfg["staff"].index(staff_cfg) % len(STAFF_EVENT_COLORS)]
    return body


def seeded_event_ids(cal: GoogleCalendar, calendar_id: str) -> list:
    ids, page = [], None
    with cal._lock:
        while True:
            resp = cal.api.events().list(calendarId=calendar_id, privateExtendedProperty="source=seed",
                                         maxResults=2500, pageToken=page).execute()
            ids += [e["id"] for e in resp.get("items", [])]
            page = resp.get("nextPageToken")
            if not page:
                return ids


def cmd_seed(args):
    cal = get_calendar()
    if not cal:
        raise SystemExit(f"no service account key at {settings.GOOGLE_SERVICE_ACCOUNT_FILE}")
    store = Store(settings.DB_PATH)
    configs = booking_configs()
    for business_id in args.only or configs:
        if business_id not in configs:
            raise SystemExit(f"{business_id} has no booking: block in seeds.yaml")
        calendar_id = store.get_calendar_id(business_id)
        if not calendar_id:
            print(f"- {business_id}: no calendar yet, run: python -m app.gcal setup")
            continue
        old = seeded_event_ids(cal, calendar_id)
        if old and not (args.clear or args.replace):
            print(f"- {business_id}: already has {len(old)} fake bookings (use --replace or --clear)")
            continue
        if old:
            cal.delete_many(calendar_id, old)
            print(f"- {business_id}: removed {len(old)} fake bookings")
        if args.clear:
            continue
        bodies = fake_events(business_id, configs[business_id], random.Random(business_id))
        ok = cal.insert_many(calendar_id, bodies)
        print(f"- {business_id}: added {ok}/{len(bodies)} fake bookings")
    sync_all(store, cal)


def cmd_sync(args):
    cal = get_calendar()
    if not cal:
        raise SystemExit(f"no service account key at {settings.GOOGLE_SERVICE_ACCOUNT_FILE}")
    store = Store(settings.DB_PATH)
    for business_id, cfg in booking_configs().items():
        started = _time.time()
        try:
            n = sync_business(store, cal, business_id, cfg)
            print(f"- {business_id}: {n} events ({_time.time() - started:.1f}s)")
        except Exception as e:
            print(f"- {business_id}: FAILED {e}")


def main():
    parser = argparse.ArgumentParser(prog="python -m app.dashboard")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync", help="pull all linked calendars once").set_defaults(func=cmd_sync)
    p = sub.add_parser("seed", help="fill calendars with fake bookings")
    p.add_argument("--only", nargs="*", help="business ids (default: all bookable)")
    p.add_argument("--replace", action="store_true", help="delete old fake bookings first")
    p.add_argument("--clear", action="store_true", help="only delete fake bookings")
    p.set_defaults(func=cmd_seed)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
