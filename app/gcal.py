"""Google Calendar access through a service account.

    python -m app.gcal setup    # create one calendar per bookable demo business and share it
    python -m app.gcal status   # check the key works and list the linked calendars

The service account owns the calendars and shares them with
BOOKING_CALENDAR_SHARE_WITH, so they show up in that person's Google Calendar.
"""
import argparse
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from .config import settings

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class GoogleCalendar:
    def __init__(self, key_file: str = "", key_info: Optional[dict] = None):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        if key_info:
            creds = service_account.Credentials.from_service_account_info(key_info, scopes=SCOPES)
        else:
            creds = service_account.Credentials.from_service_account_file(key_file, scopes=SCOPES)
        self.email = creds.service_account_email
        self.api = build("calendar", "v3", credentials=creds, cache_discovery=False)
        # googleapiclient's HTTP transport isn't thread-safe; webhook work runs in a thread pool.
        self._lock = threading.Lock()

    def events(self, calendar_id: str, start: datetime, end: datetime,
               show_deleted: bool = False) -> List[dict]:
        items, page = [], None
        with self._lock:
            while True:
                resp = self.api.events().list(
                    calendarId=calendar_id, timeMin=start.isoformat(), timeMax=end.isoformat(),
                    singleEvents=True, orderBy="startTime", pageToken=page, maxResults=2500,
                    showDeleted=show_deleted,
                ).execute()
                items += resp.get("items", [])
                page = resp.get("nextPageToken")
                if not page:
                    return items

    def busy(self, calendar_id: str, start: datetime, end: datetime,
             branch: Optional[str] = None) -> List[Tuple[datetime, datetime, str]]:
        """Busy intervals as (start, end, staff_id). Events booked for another branch
        don't block this one; events without a branch (e.g. added by hand) block every
        branch. staff_id is "" when the event isn't tied to one employee."""
        out = []
        for ev in self.events(calendar_id, start, end):
            if ev.get("status") == "cancelled" or ev.get("transparency") == "transparent":
                continue
            private = ev.get("extendedProperties", {}).get("private", {})
            ev_branch = private.get("branch")
            if branch and ev_branch and ev_branch != branch:
                continue
            s, e = event_times(ev, start.tzinfo)
            out.append((s, e, private.get("staff", "")))
        return out

    def create_event(self, calendar_id: str, summary: str, description: str,
                     start: datetime, end: datetime, location: str = "",
                     private: Optional[dict] = None, color_id: str = "") -> dict:
        body = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {"dateTime": start.isoformat(), "timeZone": settings.BOOKING_TIMEZONE},
            "end": {"dateTime": end.isoformat(), "timeZone": settings.BOOKING_TIMEZONE},
            "extendedProperties": {"private": private or {}},
            "reminders": {"useDefault": True},
        }
        if color_id:
            body["colorId"] = color_id
        with self._lock:
            return self.api.events().insert(calendarId=calendar_id, body=body).execute()

    def move_event(self, calendar_id: str, event_id: str, start: datetime, end: datetime) -> dict:
        body = {"start": {"dateTime": start.isoformat(), "timeZone": settings.BOOKING_TIMEZONE},
                "end": {"dateTime": end.isoformat(), "timeZone": settings.BOOKING_TIMEZONE}}
        with self._lock:
            return self.api.events().patch(calendarId=calendar_id, eventId=event_id,
                                           body=body).execute()

    def insert_many(self, calendar_id: str, bodies: List[dict]) -> int:
        """Insert events in batches of 50, retrying rate-limited ones; returns how many succeeded."""
        pending, ok = list(bodies), 0
        for attempt in range(5):
            failed = []
            for i in range(0, len(pending), 50):
                chunk = pending[i:i + 50]

                def done(request_id, _resp, exc, chunk=chunk):
                    if exc:
                        failed.append((chunk[int(request_id)], exc))
                with self._lock:
                    batch = self.api.new_batch_http_request(callback=done)
                    for n, body in enumerate(chunk):
                        batch.add(self.api.events().insert(calendarId=calendar_id, body=body),
                                  request_id=str(n))
                    batch.execute()
                time.sleep(0.5)
            ok += len(pending) - len(failed)
            if not failed:
                break
            print(f"[gcal] {len(failed)} inserts failed (e.g. {str(failed[0][1])[:120]}), retrying")
            pending = [f[0] for f in failed]
            time.sleep(5 * (attempt + 1))
        return ok

    def delete_many(self, calendar_id: str, event_ids: List[str]):
        for i in range(0, len(event_ids), 50):
            with self._lock:
                batch = self.api.new_batch_http_request()
                for eid in event_ids[i:i + 50]:
                    batch.add(self.api.events().delete(calendarId=calendar_id, eventId=eid))
                batch.execute()

    def create_calendar(self, name: str) -> str:
        with self._lock:
            cal = self.api.calendars().insert(
                body={"summary": name, "timeZone": settings.BOOKING_TIMEZONE}).execute()
        return cal["id"]

    def share(self, calendar_id: str, email: str, role: str = "owner"):
        with self._lock:
            self.api.acl().insert(
                calendarId=calendar_id, sendNotifications=True,
                body={"role": role, "scope": {"type": "user", "value": email}},
            ).execute()


def event_times(ev: dict, tz) -> Tuple[datetime, datetime]:
    s, e = ev["start"], ev["end"]
    if "dateTime" in s:
        return datetime.fromisoformat(s["dateTime"]), datetime.fromisoformat(e["dateTime"])
    # all-day event covers the whole day
    return (datetime.fromisoformat(s["date"]).replace(tzinfo=tz),
            datetime.fromisoformat(e["date"]).replace(tzinfo=tz))


def get_calendar() -> Optional[GoogleCalendar]:
    """None when no key is configured, so booking still works without Google.
    The key comes from GOOGLE_SERVICE_ACCOUNT_JSON (hosting) or the key file (local)."""
    try:
        if settings.GOOGLE_SERVICE_ACCOUNT_JSON:
            return GoogleCalendar(key_info=json.loads(settings.GOOGLE_SERVICE_ACCOUNT_JSON))
        if Path(settings.GOOGLE_SERVICE_ACCOUNT_FILE).exists():
            return GoogleCalendar(settings.GOOGLE_SERVICE_ACCOUNT_FILE)
    except Exception as e:
        print(f"[gcal] could not load the service account key: {e}")
    return None


def share_list() -> List[str]:
    """BOOKING_CALENDAR_SHARE_WITH may list several people, comma-separated."""
    return [e.strip() for e in settings.BOOKING_CALENDAR_SHARE_WITH.split(",") if e.strip()]


def ensure_calendar(store, cal: "GoogleCalendar", business_id: str, title: str) -> str:
    """The business's booking calendar, created (and shared) when it has none yet."""
    calendar_id = store.get_calendar_id(business_id)
    if calendar_id:
        return calendar_id
    calendar_id = cal.create_calendar(title)
    store.set_calendar_id(business_id, calendar_id)
    for email in share_list():
        try:
            cal.share(calendar_id, email)
        except Exception as e:
            print(f"[gcal] could not share {business_id}'s calendar with {email}: {e}")
    print(f"[gcal] created a calendar for {business_id}: {calendar_id}")
    return calendar_id


def cmd_setup(args):
    from .demo_data import load_seeds
    from .store import Store

    cal = get_calendar()
    if not cal:
        raise SystemExit(f"no service account key at {settings.GOOGLE_SERVICE_ACCOUNT_FILE}")
    share_with = settings.BOOKING_CALENDAR_SHARE_WITH
    if not share_with:
        raise SystemExit("set BOOKING_CALENDAR_SHARE_WITH in .env")
    store = Store(settings.DB_PATH)
    print(f"service account: {cal.email}")
    # Seeds, not the businesses table: the dashboard needs a calendar even before
    # a business's FAQ data has been generated and loaded.
    seeds = load_seeds()
    targets = list(seeds["businesses"])
    if "ajilt_ai" in seeds:  # Ajilt-AI's own sales-meeting calendar
        targets.append({"id": "ajilt_ai", **seeds["ajilt_ai"]})
    for biz in targets:
        if "booking" not in biz:
            continue
        calendar_id = store.get_calendar_id(biz["id"])
        if calendar_id:
            print(f"- {biz['id']}: already linked ({calendar_id})")
            continue
        title = ("Ажилт-AI · борлуулалтын уулзалт" if biz["id"] == "ajilt_ai"
                 else f"{biz['name']['mn']} · Ajilt-AI демо")
        calendar_id = ensure_calendar(store, cal, biz["id"], title)
        print(f"- {biz['id']}: created and shared with {share_with}\n    {calendar_id}")


def cmd_status(args):
    from .store import Store

    cal = get_calendar()
    if not cal:
        raise SystemExit(f"no service account key at {settings.GOOGLE_SERVICE_ACCOUNT_FILE}")
    print(f"service account: {cal.email}")
    store = Store(settings.DB_PATH)
    for biz in store.list_businesses():
        calendar_id = store.get_calendar_id(biz["id"])
        if not calendar_id:
            continue
        with cal._lock:
            meta = cal.api.calendars().get(calendarId=calendar_id).execute()
        print(f"- {biz['id']}: OK '{meta['summary']}' ({meta['timeZone']})")


def main():
    parser = argparse.ArgumentParser(prog="python -m app.gcal")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup", help="create and share demo calendars").set_defaults(func=cmd_setup)
    sub.add_parser("status", help="check calendar access").set_defaults(func=cmd_status)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
