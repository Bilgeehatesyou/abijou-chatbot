"""The chatbot <-> bas.mn (Perfex CRM) sync.

Outgoing, queued in `crm_outbox` next to the booking it describes and sent right after
(by the background worker, or inline on serverless), retried with backoff:

  booking   new booking         -> bas.mn customer (found by phone, else created with branch /
                                   language / channel) + a calendar appointment
  status    staff change status -> appointment colour (blue booked, green came, grey
                                   cancelled / no-show); "came" also makes the invoice:
                                   the branch's currency, the treatment from the price list,
                                   the branch and booking number in its custom fields

Incoming, `pull()` every BASMN_PULL_SECONDS (bas.mn's webhooks don't fire on staff edits):

  appointment deleted in bas.mn           -> booking cancelled, its slot free again
  appointment title starts with "ИРСЭН"   -> booking done, invoice made (data/basmn.yaml:
                                             came_markers)
  appointment moved                       -> booking moved
  invoice paid / partly paid              -> booking's payment status
  appointments staff add by hand          -> those times are busy in the chatbot

Tenant ids (currencies, payment modes, countries, custom field labels) are in
data/basmn.yaml, so another clinic only needs its own copy of that file.

    python -m app.crm check      # read-only: key, custom fields, ids in data/basmn.yaml
    python -m app.crm status     # queue and last pull
    python -m app.crm flush | pull | retry
"""
import argparse
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional
from zoneinfo import ZoneInfo

import yaml

from .basmn import BasError, BasMN, RateLimited, configured, digits
from .clinic import Clinic, get_clinic, tr
from .config import settings

CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "basmn.yaml"
MAX_ATTEMPTS = 12               # ~ a day of retries before a job is parked as failed
WORKER_IDLE_SECONDS = 20
INLINE_JOBS = 5                 # serverless: jobs sent before the response returns
CUSTOMER_REFRESH_SECONDS = 3600
OPEN = ("new", "confirmed")
INVOICE_STATUS = {"1": "unpaid", "2": "paid", "3": "partial", "4": "unpaid"}   # 4 = overdue

_config: Optional[dict] = None
_kick = threading.Event()


class NotReady(Exception):
    """A job depends on one that hasn't been sent yet; try again later."""


def config() -> dict:
    global _config
    if _config is None:
        _config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return _config


def _client() -> Optional[BasMN]:
    return BasMN() if configured() else None


# ---------- queueing ----------
def enqueue(store, kind: str, booking_id, payload: Optional[dict] = None):
    """Record work for bas.mn. Never raises: a CRM hiccup must not lose the booking."""
    if not configured():
        return
    try:
        store.crm_enqueue(kind, booking_id, payload)
    except Exception as e:
        print(f"[crm] could not queue {kind} {booking_id}: {type(e).__name__}: {e}")
        return
    if settings.SERVERLESS:
        flush(store, limit=INLINE_JOBS)     # nothing runs after the response there
    else:
        _kick.set()


def flush(store, limit: int = 50, bas: Optional[BasMN] = None,
          clinic: Optional[Clinic] = None) -> Dict[str, int]:
    bas, clinic = bas or _client(), clinic or get_clinic()
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
            handler(store, bas, clinic, job["ref_id"], job["payload"])
        except (NotReady, RateLimited) as e:
            store.crm_retry(job["id"], f"waiting: {e}", 60 if isinstance(e, NotReady) else 300)
            result["retry"] += 1
        except Exception as e:
            attempts = job["attempts"] + 1
            give_up = attempts >= MAX_ATTEMPTS or isinstance(e, (ValueError, KeyError))
            store.crm_retry(job["id"], f"{type(e).__name__}: {e}", min(30 * 2 ** job["attempts"], 3600), give_up)
            result["failed" if give_up else "retry"] += 1
            print(f"[crm] {job['kind']} {job['ref_id']} failed (try {attempts}): {e}")
        else:
            store.crm_finish(job["id"])
            result["sent"] += 1
    return result


# ---------- naming, shared with the price list in bas.mn ----------
def item_name(name: dict, country: str) -> str:
    """How a treatment is called in bas.mn Items (tools/basmn_demo.py and the price list)."""
    return ("🇲🇳 " + name["mn"]) if country == "mn" else f"🇰🇷 {name['mn']} / {name['ko']}"


def booking_ref(b: dict) -> str:
    return f"BK-{b['start_at'][:10].replace('-', '')}-{b['id']:03d}"


def _local(iso: str) -> datetime:
    """Our ISO time (in the branch's zone) as the naive time bas.mn stores."""
    return datetime.fromisoformat(iso).replace(tzinfo=None, second=0, microsecond=0)


def _bas_time(text: str) -> Optional[datetime]:
    try:
        return datetime.strptime((text or "")[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def event_title(b: dict, clinic: Clinic) -> str:
    """Short, so it reads in the month view: "Каннам · Excel-V лазер · Б. Хулан".
    The status is the colour, not part of the title."""
    branch, service = clinic.branch(b["branch_id"]), clinic.service(b["service_id"])
    place = tr(branch["name"], "mn").split(" · ")[-1]
    return f"{place} · {tr(service['short'], 'mn')} · {b['name']}"


def _color(status: str) -> str:
    colors = config()["colors"]
    return colors.get(status) or colors["booked"]


def _field_ids(store, bas: BasMN) -> Dict[str, int]:
    """Custom field ids, found once by the labels in data/basmn.yaml."""
    ids = store.crm_state_get("custom_field_ids")
    if ids is None:
        found = {"customer": bas.custom_fields("customers"), "invoice": bas.custom_fields("invoice")}
        ids = {}
        for key, label in config().get("custom_fields", {}).items():
            kind = "invoice" if key.startswith("invoice_") else "customer"
            if label in found[kind]:
                ids[key] = found[kind][label]
        store.crm_state_set("custom_field_ids", ids)
    return ids


# ---------- customers ----------
def _phone_key(phone) -> str:
    return digits(phone)[-8:]


def customer_for(store, bas: BasMN, clinic: Clinic, b: dict) -> str:
    """The bas.mn customer with this phone, else a new one. bas.mn's search is broken, so
    known phones are kept here and refreshed from the full customer list now and then."""
    key = _phone_key(b["phone"])
    known = store.crm_state_get("customers_by_phone", {})
    if key not in known and time.time() - store.crm_state_get("customers_refreshed", 0) > CUSTOMER_REFRESH_SECONDS:
        rows = bas.customers()
        for c in rows:
            if _phone_key(c.get("phonenumber")):
                known[_phone_key(c["phonenumber"])] = str(c["userid"])
        note_customer_count(store, len(rows))
        store.crm_state_set("customers_by_phone", known)
        store.crm_state_set("customers_refreshed", time.time())
    if key in known:
        return known[key]
    cfg, ids = config(), _field_ids(store, bas)
    branch = clinic.branch(b["branch_id"])
    fields = {"company": b["name"], "phonenumber": b["phone"], "country": cfg["countries"][b["country"]],
              "billing_country": cfg["countries"][b["country"]]}
    values = {"customer_branch": tr(branch["name"], "mn"),
              "customer_language": cfg["language_names"].get(b["lang"], ""),
              "customer_channel": cfg["channel_names"].get(b["channel"], "")}
    for key_name, value in values.items():
        if key_name in ids and value:
            fields[f"custom_fields[customers][{ids[key_name]}]"] = value
    customer_id = bas.create_customer(fields)
    known[key] = customer_id
    store.crm_state_set("customers_by_phone", known)
    note_customer_count(store, store.crm_state_get("customer_count", 0) + 1)
    return customer_id


def note_customer_count(store, count: int):
    """Remember how many customers bas.mn has, and warn in the log as it nears the plan's cap
    (data/basmn.yaml): past it bas.mn refuses new patients."""
    store.crm_state_set("customer_count", count)
    limit, warn_at = config().get("customer_limit"), config().get("customer_warn_at")
    if limit and warn_at and count >= warn_at:
        print(f"[crm] WARNING: bas.mn has {count} of its {limit} customers; "
              f"from {limit} on, new patients can't be added there")


# ---------- handlers ----------
def push_booking(store, bas: BasMN, clinic: Clinic, booking_id, payload: dict):
    b = store.get_booking(booking_id)
    if not b or b["crm_event_id"]:
        return
    customer_id = b["crm_customer_id"] or customer_for(store, bas, clinic, b)
    store.update_booking(b["id"], crm_customer_id=customer_id)
    branch, service = clinic.branch(b["branch_id"]), clinic.service(b["service_id"])
    title, start = event_title(b, clinic), _local(b["start_at"])
    # a retried job may have made it already: look before creating
    event_id = bas.find_event(title, start) or bas.create_event(
        title=title, start=start, end=_local(b["end_at"]), color=_color(b["status"]),
        staff_id=config().get("staff_id", 1),
        description=(f"{booking_ref(b)}\nУтас: {b['phone']}\nЭмчилгээ: {tr(service['name'], 'mn')}\n"
                     f"Салбар: {tr(branch['name'], 'mn')}\n"
                     f"Суваг: {config()['channel_names'].get(b['channel'], b['channel'])} (чатбот)"
                     + (f"\nТэмдэглэл: {b['note']}" if b.get("note") else "")))
    if not event_id:
        raise BasError("appointment not found after create")
    store.update_booking(b["id"], crm_event_id=event_id)


def push_status(store, bas: BasMN, clinic: Clinic, booking_id, payload: dict):
    b = store.get_booking(booking_id)
    if not b:
        return
    if not b["crm_event_id"]:
        if store.crm_has_pending("booking", booking_id):
            raise NotReady("the appointment isn't in bas.mn yet")
        push_booking(store, bas, clinic, booking_id, {})
        b = store.get_booking(booking_id)
    status = payload.get("status") or b["status"]
    event = next((e for e in bas.events() if e["id"] == b["crm_event_id"]), None)
    if event and event["color"] != _color(status):
        bas.update_event(event, color=_color(status))
    if status == "done" and not b["crm_invoice_id"]:
        make_invoice(store, bas, clinic, b)


def make_invoice(store, bas: BasMN, clinic: Clinic, b: dict):
    """The invoice for a visit, as staff would make it: the price-list line, the branch's
    currency and payment modes, the branch and booking number. Staff can edit it after."""
    if not b["price"]:
        return                                          # free consultation: nothing to bill
    cfg, ids = config(), _field_ids(store, bas)
    branch, service = clinic.branch(b["branch_id"]), clinic.service(b["service_id"])
    customer_id = b["crm_customer_id"] or customer_for(store, bas, clinic, b)
    option = next((o for o in service.get("options", []) if o.get(b["currency"]) == b["price"]), None)
    description = (item_name(option["name"], b["country"]) if option
                   else f"{item_name(service['name'], b['country'])} · 1 удаа")
    # bas.mn needs a number and ignores a prefix, so the bot numbers in its own range, far
    # above the one staff count up from: the two never collide
    first = int(cfg.get("invoice_numbers_from", 900001))
    number = max(first - 1, bas.last_invoice_number(), store.crm_state_get("last_invoice_number", 0)) + 1
    day = b["start_at"][:10]
    data = {"clientid": customer_id, "number": str(number), "date": day, "duedate": day,
            "currency": cfg["currencies"][b["currency"]],
            "subtotal": f"{b['price']:.2f}", "total": f"{b['price']:.2f}",
            "billing_street": tr(branch["address"], "mn"), "billing_country": cfg["countries"][b["country"]],
            "clientnote": cfg.get("invoice_note", ""),
            "newitems[0][description]": description, "newitems[0][long_description]": "",
            "newitems[0][qty]": "1", "newitems[0][rate]": f"{b['price']:.2f}",
            "newitems[0][unit]": "удаа", "newitems[0][order]": "1"}
    for i, mode in enumerate(cfg["payment_modes"][b["country"]]):
        data[f"allowed_payment_modes[{i}]"] = mode
    if "invoice_branch" in ids:
        data[f"custom_fields[invoice][{ids['invoice_branch']}]"] = tr(branch["name"], "mn")
    if "invoice_booking" in ids:
        data[f"custom_fields[invoice][{ids['invoice_booking']}]"] = booking_ref(b)
    invoice = bas.create_invoice(data)
    store.crm_state_set("last_invoice_number", number)
    store.update_booking(b["id"], crm_customer_id=customer_id, crm_invoice_id=str(invoice["id"]),
                         crm_invoice_number=str(number), payment_status="unpaid",
                         payment_link=bas.invoice_link(invoice))


HANDLERS = {"booking": push_booking, "status": push_status}


# ---------- reading bas.mn back ----------
def _came(title: str) -> bool:
    low = title.strip().lower()
    return any(low.startswith(m.lower()) for m in config().get("came_markers", []))


def pull(store, bas: Optional[BasMN] = None, clinic: Optional[Clinic] = None) -> dict:
    bas, clinic = bas or _client(), clinic or get_clinic()
    if not bas:
        return {}
    events = {e["id"]: e for e in bas.events()}
    changes = {"cancelled": 0, "came": 0, "moved": 0, "paid": 0}
    ours = set()
    for b in store.crm_bookings():
        if b["crm_event_id"]:
            ours.add(b["crm_event_id"])
        event = events.get(b["crm_event_id"]) if b["crm_event_id"] else None
        if b["status"] in OPEN and b["crm_event_id"]:
            if not event:                                       # deleted in bas.mn
                store.update_booking(b["id"], status="cancelled")
                changes["cancelled"] += 1
                continue
            if _came(event["title"]):
                store.update_booking(b["id"], status="done")
                enqueue(store, "status", b["id"], {"status": "done"})
                changes["came"] += 1
            start, end = _bas_time(event["start"]), _bas_time(event["end"])
            if start and start != _local(b["start_at"]):         # moved in bas.mn
                tz = ZoneInfo(clinic.country_of(clinic.branch(b["branch_id"]))["tz"])
                length = datetime.fromisoformat(b["end_at"]) - datetime.fromisoformat(b["start_at"])
                new_end = end if end and end > start else start + length
                store.update_booking(b["id"], start_at=start.replace(tzinfo=tz).isoformat(),
                                     end_at=new_end.replace(tzinfo=tz).isoformat())
                changes["moved"] += 1
        if b["crm_invoice_id"] and b["payment_status"] in ("unpaid", "partial", "pending"):
            invoice = bas.invoice(b["crm_invoice_id"])
            state = INVOICE_STATUS.get(str((invoice or {}).get("status")))
            if state and state != b["payment_status"]:
                store.update_booking(b["id"], payment_status=state)
                changes["paid"] += state == "paid"
    store.crm_state_set("busy_events", _busy_events(events.values(), ours, clinic))
    note_customer_count(store, len(bas.customers()))
    store.crm_state_set("last_pull", {"at": time.time(), **changes})
    return changes


def _busy_events(events, ours: set, clinic: Clinic) -> list:
    """Appointments staff put in bas.mn by hand (phone, walk-in) block their branch's slots.
    The branch is the one whose name appears in the title or description."""
    out = []
    for e in events:
        if e["id"] in ours or e.get("color") == config()["colors"]["cancelled"]:
            continue
        start, end = _bas_time(e["start"]), _bas_time(e["end"])
        text = f"{e['title']} {e['description']}"
        branch = next((b for b in clinic.branches if tr(b["name"], "mn").split(" · ")[-1] in text), None)
        if start and branch:
            out.append({"branch": branch["id"], "start": start.isoformat(),
                        "end": (end if end and end > start else start + timedelta(minutes=60)).isoformat()})
    return out


def busy(store, branch_id: str) -> list:
    """(start, end) naive local times of hand-made bas.mn appointments at this branch."""
    return [(datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"]))
            for e in store.crm_state_get("busy_events", []) if e["branch"] == branch_id]


# ---------- background worker (servers; serverless flushes inline) ----------
class CrmWorker:
    def __init__(self, store):
        self.store = store
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
                    pull(self.store)
            except Exception as e:
                print(f"[crm] worker: {type(e).__name__}: {e}")
            _kick.wait(WORKER_IDLE_SECONDS)


def status(store) -> dict:
    return {"configured": configured(), "queue": store.crm_counts(),
            "last_pull": store.crm_state_get("last_pull"),
            "customers": store.crm_state_get("customer_count"),
            "failed": [{k: j[k] for k in ("kind", "ref_id", "attempts", "last_error")}
                       for j in store.crm_jobs("failed", 10)]}


def check(bas: BasMN) -> list:
    """Read-only: does the key work, and do the ids in data/basmn.yaml exist?"""
    cfg, lines = config(), []
    for kind, keys in (("customers", "customer_"), ("invoice", "invoice_")):
        found = bas.custom_fields(kind)
        for key, label in cfg.get("custom_fields", {}).items():
            if key.startswith(keys):
                lines.append(f"custom field {key} '{label}': " + (f"id {found[label]}" if label in found
                                                                   else "MISSING in bas.mn"))
    lines.append(f"customers in bas.mn: {len(bas.customers())}")
    lines.append(f"last invoice number: {bas.last_invoice_number()}")
    lines.append(f"appointments in the calendar: {len(bas.events())}")
    lines.append(f"currencies (not readable through the API, check by hand): {cfg['currencies']}")
    lines.append(f"payment modes per country: {cfg['payment_modes']}")
    return lines


def main():
    import sys
    from .store import Store
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m app.crm")
    parser.add_argument("cmd", choices=["check", "status", "flush", "pull", "retry"])
    args = parser.parse_args()
    if not configured():
        raise SystemExit("set BASMN_URL and BASMN_API_KEY in .env")
    store = Store(settings.DB_PATH)
    if args.cmd == "check":
        print("\n".join(check(BasMN())))
    elif args.cmd == "status":
        print(status(store))
    elif args.cmd == "flush":
        print(flush(store))
    elif args.cmd == "pull":
        print(pull(store))
    else:
        print(f"requeued {store.crm_requeue_failed()} failed jobs")


if __name__ == "__main__":
    main()
