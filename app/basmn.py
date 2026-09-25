"""bas.mn (Perfex CRM) client.

What the chatbot collects — leads, bookings, orders — belongs in the client's
own CRM, not only in our dashboard. This is the thin layer that puts it there.

Checked against a live tenant, because the published Swagger is incomplete:

* auth is the header `authtoken`; every other spelling answers "Token is not found"
* a create returns `{"status": true, ...}`; leads also return `record_id`, but a
  calendar event does not, so `find_event` matches it back by title and start
* `POST /api/calendar` really requires reminder_before, reminder_before_type,
  isstartnotified and public on top of the documented fields
* an empty list answers **404** `{"status": false, "message": "No data were found"}`,
  which is not an error
* `GET /api/calendar` takes no parameters at all — everything comes back, so
  callers should mirror it rather than ask per request
"""
from datetime import datetime
from typing import List, Optional

import httpx

from .config import settings

TIMEOUT = 20
EMPTY = "no data were found"


class BasError(RuntimeError):
    """The CRM refused a call. The message is theirs, cleaned of HTML."""


def configured() -> bool:
    return bool(settings.BASMN_URL and settings.BASMN_API_KEY)


class BasMN:
    def __init__(self, url: str = "", key: str = ""):
        self.url = (url or settings.BASMN_URL).rstrip("/")
        self.key = key or settings.BASMN_API_KEY

    # ---- plumbing ----
    def _headers(self) -> dict:
        return {"authtoken": self.key, "Accept": "application/json"}

    def _call(self, method: str, path: str, **kw):
        try:
            r = httpx.request(method, f"{self.url}/api{path}", headers=self._headers(),
                              timeout=TIMEOUT, follow_redirects=True, **kw)
        except httpx.HTTPError as e:
            raise BasError(f"{type(e).__name__}: {e}") from e
        try:
            body = r.json()
        except ValueError:
            raise BasError(f"HTTP {r.status_code}: {r.text[:200]}")

        if isinstance(body, dict) and body.get("status") is False:
            message = _plain(body.get("message") or "")
            if EMPTY in message.lower():        # an empty list, not a failure
                return []
            errors = body.get("error")
            if isinstance(errors, dict) and errors:
                message = "; ".join(f"{k}: {_plain(v)}" for k, v in errors.items())
            raise BasError(message or f"HTTP {r.status_code}")
        return body

    def _get(self, path: str):
        body = self._call("GET", path)
        if isinstance(body, dict):
            return body.get("data", body)
        return body

    def _post(self, path: str, payload: dict) -> dict:
        body = self._call("POST", path, json=payload)
        return body if isinstance(body, dict) else {}

    # ---- reads ----
    def staff(self) -> list:
        """Everyone who can be assigned work. Note their API also returns the
        password hash; we keep only what we need."""
        rows = self._get("/staffs/search/a") or []
        return [{"id": str(s.get("staffid")), "name": f"{s.get('firstname','')} {s.get('lastname','')}".strip(),
                 "email": s.get("email", "")} for s in rows]

    def items(self) -> list:
        """The client's own products and prices, so the bot quotes real numbers."""
        rows = self._get("/items") or []
        return [{"id": str(i.get("id")), "name": i.get("description", ""),
                 "long_description": i.get("long_description", ""),
                 "rate": i.get("rate"), "unit": i.get("unit", "")} for i in rows]

    def events(self) -> list:
        """Every calendar event — their API has no date filter, so mirror this."""
        rows = self._get("/calendar") or []
        return [{"id": str(e.get("eventid")), "title": e.get("title", ""),
                 "start": e.get("start", ""), "end": e.get("end", ""),
                 "staff_id": str(e.get("userid", "")), "description": e.get("description", "")}
                for e in rows]

    # ---- writes ----
    def create_lead(self, name: str, phone: str = "", email: str = "", note: str = "",
                    source: int = 1, status: int = 1, assigned: int = 1,
                    company: str = "") -> Optional[str]:
        """Returns the new lead's id (their `record_id`), when they send one."""
        body = self._post("/leads", {
            "name": name, "source": source, "status": status, "assigned": assigned,
            "phonenumber": phone, "email": email, "description": note, "company": company,
        })
        record = body.get("record_id")
        return str(record) if record is not None else None

    def create_event(self, title: str, start: datetime, end: datetime, staff_id: int = 1,
                     description: str = "", color: str = "", reminder_minutes: int = 30) -> Optional[str]:
        """Creates the appointment and returns its id, found by reading back."""
        self._post("/calendar", {
            "title": title, "description": description,
            "start": start.strftime("%Y-%m-%d %H:%M:%S"),
            "end": end.strftime("%Y-%m-%d %H:%M:%S"),
            "userid": staff_id, "color": color or "#16A34A",
            # Undocumented but required:
            "reminder_before": reminder_minutes, "reminder_before_type": "minute",
            "isstartnotified": 0, "public": 1,
        })
        return self.find_event(title, start)

    def find_event(self, title: str, start: datetime) -> Optional[str]:
        """A created event comes back without an id, so match it by title + start."""
        stamp = start.strftime("%Y-%m-%d %H:%M")
        for e in self.events():
            if e["title"] == title and e["start"].startswith(stamp):
                return e["id"]
        return None

    def delete_event(self, event_id: str) -> bool:
        self._call("DELETE", f"/calendar/{event_id}")
        return True

    def create_customer(self, company: str, phone: str = "", email: str = "",
                        address: str = "") -> dict:
        """In Perfex the customer is the company; the person is a contact."""
        return self._post("/customers", {"company": company, "phone": phone,
                                         "email": email, "address": address})

    # ---- orders ----
    def add_row(self, table: str, row: dict) -> dict:
        """Perfex has no order object, so orders live in a custom table."""
        return self._post(f"/thirdparty/customtable/{table}", row)

    def rows(self, table: str) -> list:
        return self._get(f"/thirdparty/customtable/{table}") or []


def _plain(html: str) -> str:
    """Their errors arrive as HTML paragraphs."""
    text = str(html).replace("</p>", " ").replace("<p>", "")
    return " ".join(text.split())
