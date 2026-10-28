"""bas.mn (Perfex CRM) client: the thin layer the sync in app/crm.py talks through.

Checked against a live tenant, because the published API docs are incomplete:

* auth is the header `authtoken`
* an empty list answers 404 {"status": false, "message": "No data were found"}: not an error
* lists come in pages: {"data": [...], "meta": {"last_page": n}}
* creates answer {"status": true, "record_id": n} for customers, but invoices and calendar
  events come back without an id: invoices are found by number, events by title + start
* recording a payment answers HTTP 500 and updating an invoice "Invoice Update Fail",
  although both are saved: callers read the result back instead of trusting the reply
* an invoice update must send the whole invoice (number, date, items...), not only changes
* /customers/search/... answers 500, so customers are matched by phone from the full list
* a tenant at its plan's customer limit answers a create with a 303 to /admin/
* only the newest invoice can be deleted
"""
import re
from datetime import datetime
from typing import Dict, List, Optional

import httpx

from .config import settings

TIMEOUT = 25
EMPTY = "no data were found"


class BasError(RuntimeError):
    """bas.mn refused a call. The message is theirs, cleaned of HTML."""


class RateLimited(BasError):
    """Over the key's quota; the sync tries again later."""


def configured() -> bool:
    return bool(settings.BASMN_URL and settings.BASMN_API_KEY)


def digits(text) -> str:
    return re.sub(r"\D", "", str(text or ""))


def plain(html) -> str:
    text = str(html).replace("</p>", " ").replace("<p>", "")
    return " ".join(text.split())


def stamp(dt: datetime) -> str:
    """bas.mn stores naive local times."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class BasMN:
    def __init__(self, url: str = "", key: str = ""):
        self.url = (url or settings.BASMN_URL).rstrip("/")
        self.key = key or settings.BASMN_API_KEY

    # ---- plumbing ----
    def _call(self, method: str, path: str, ok_errors: bool = False, **kw):
        try:
            r = httpx.request(method, f"{self.url}/api{path}", headers={"authtoken": self.key},
                              timeout=TIMEOUT, **kw)
        except httpx.HTTPError as e:
            raise BasError(f"{type(e).__name__}: {e}") from e
        if r.status_code == 429:
            raise RateLimited("over the API key's quota")
        if r.status_code in (301, 302, 303):
            raise BasError(f"bas.mn redirected to {r.headers.get('location', '?')} "
                           "(a plan limit, e.g. the number of customers)")
        try:
            body = r.json()
        except ValueError:
            if ok_errors:
                return None
            raise BasError(f"HTTP {r.status_code}: {plain(r.text)[:160]}")
        if isinstance(body, dict) and body.get("status") is False:
            message = plain(body.get("message") or "")
            if EMPTY in message.lower():
                return []
            if ok_errors:
                return body
            errors = body.get("error")
            if isinstance(errors, dict) and errors:
                message = "; ".join(f"{k}: {plain(v)}" for k, v in errors.items())
            raise BasError(message or f"HTTP {r.status_code}")
        return body

    def _get(self, path: str):
        return self._call("GET", path)

    def _rows(self, path: str) -> List[dict]:
        """Every row of a list endpoint, through all its pages."""
        out, page = [], 1
        while True:
            body = self._call("GET", path, params={"page": page})
            if isinstance(body, list):
                return out + body
            out += body.get("data", []) if isinstance(body, dict) else []
            if page >= ((body or {}).get("meta") or {}).get("last_page", 1):
                return out
            page += 1

    def _post(self, path: str, data: dict) -> dict:
        body = self._call("POST", path, data=data)
        return body if isinstance(body, dict) else {}

    # ---- setup ----
    def custom_fields(self, kind: str) -> Dict[str, int]:
        """{label: id} of the custom fields on customers / invoice."""
        rows = self._get(f"/custom_fields/{kind}") or []
        return {f["label"]: int(f["custom_field_id"]) for f in rows if isinstance(f, dict)}

    # ---- customers ----
    def customers(self) -> List[dict]:
        return self._rows("/customers")

    def create_customer(self, fields: dict) -> str:
        body = self._post("/customers", fields)
        if not body.get("record_id"):
            raise BasError(f"customer not created: {body}")
        return str(body["record_id"])

    # ---- calendar ----
    def events(self) -> List[dict]:
        """Every calendar event: the API has no date filter."""
        rows = self._get("/calendar") or []
        return [{"id": str(e.get("eventid")), "title": e.get("title", ""), "start": e.get("start", ""),
                 "end": e.get("end") or "", "description": e.get("description") or "",
                 "color": e.get("color", ""), "userid": e.get("userid")} for e in rows]

    def create_event(self, *, title: str, start: datetime, end: datetime, description: str,
                     color: str, staff_id: int = 1) -> Optional[str]:
        self._post("/calendar", {
            "title": title, "description": description, "start": stamp(start), "end": stamp(end),
            "userid": staff_id, "color": color, "public": 1,
            # undocumented but required
            "reminder_before": 30, "reminder_before_type": "minute", "isstartnotified": 0})
        return self.find_event(title, start)

    def find_event(self, title: str, start: datetime) -> Optional[str]:
        when = start.strftime("%Y-%m-%d %H:%M")
        return next((e["id"] for e in self.events() if e["title"] == title and e["start"].startswith(when)),
                    None)

    def update_event(self, event: dict, **fields) -> None:
        """PUT needs every field, so the current event is sent back with the changes."""
        payload = {"title": event["title"], "description": event["description"], "start": event["start"],
                   "end": event["end"], "userid": event.get("userid") or 1, "color": event["color"],
                   "public": 1, "reminder_before": 30, "reminder_before_type": "minute",
                   "isstartnotified": 0}
        payload.update({k: stamp(v) if isinstance(v, datetime) else v for k, v in fields.items()})
        self._call("PUT", f"/calendar/{event['id']}", json=payload)

    # ---- invoices ----
    def invoice(self, invoice_id) -> Optional[dict]:
        body = self._get(f"/invoices/{invoice_id}")
        return body if isinstance(body, dict) and body.get("id") else None

    def create_invoice(self, data: dict) -> dict:
        """Creates it, then finds it by number (the create returns no id)."""
        self._post("/invoices", data)
        found = self._get(f"/invoices/search/{data['number']}") or []
        rows = found if isinstance(found, list) else found.get("data", [])
        match = next((r for r in rows if str(r.get("clientid")) == str(data["clientid"])
                      and str(r.get("number")) == str(int(data["number"]))), None)
        if not match:
            raise BasError(f"invoice {data['number']} not found after create")
        return self.invoice(match["id"])

    def last_invoice_number(self) -> int:
        rows = self._rows("/invoices")
        return max((int(r.get("number") or 0) for r in rows), default=0)

    def invoice_link(self, invoice: dict) -> str:
        """The page the patient opens to see (and pay) the invoice, no login needed."""
        return f"{self.url}/invoice/{invoice['id']}/{invoice['hash']}" if invoice.get("hash") else ""

    def record_payment(self, *, invoice_id, amount: float, date: str, mode_id: int,
                       transaction_id: str = "", note: str = "") -> None:
        # answers HTTP 500 although the payment is saved: the caller reads the invoice back
        self._call("POST", "/payments", ok_errors=True, data={
            "invoiceid": invoice_id, "amount": f"{amount:.2f}", "date": date, "paymentmode": mode_id,
            "transactionid": transaction_id, "note": note})
