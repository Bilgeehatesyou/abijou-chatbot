"""Google Calendar access through a service account (optional).

    python -m app.gcal setup    # create the clinic's booking calendar and share it
    python -m app.gcal status   # check the key works and the calendar is linked

The service account owns the calendars and shares them with
BOOKING_CALENDAR_SHARE_WITH, so they show up in that person's Google Calendar.
"""
import argparse
import json
import threading
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
        """Busy intervals as (start, end, event_id). Events booked for another branch
        don't block this one; events without a branch (e.g. added by hand) block every
        branch."""
        out = []
        for ev in self.events(calendar_id, start, end):
            if ev.get("status") == "cancelled" or ev.get("transparency") == "transparent":
                continue
            private = ev.get("extendedProperties", {}).get("private", {})
            ev_branch = private.get("branch")
            if branch and ev_branch and ev_branch != branch:
                continue
            s, e = event_times(ev, start.tzinfo)
            out.append((s, e, ev.get("id", "")))
        return out

    def create_event(self, calendar_id: str, summary: str, description: str,
                     start: datetime, end: datetime, location: str = "",
                     private: Optional[dict] = None, color_id: str = "") -> dict:
        zone = getattr(start.tzinfo, "key", settings.BOOKING_TIMEZONE)   # Seoul branches book in Seoul time
        body = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {"dateTime": start.isoformat(), "timeZone": zone},
            "end": {"dateTime": end.isoformat(), "timeZone": zone},
            "extendedProperties": {"private": private or {}},
            "reminders": {"useDefault": True},
        }
        if color_id:
            body["colorId"] = color_id
        with self._lock:
            return self.api.events().insert(calendarId=calendar_id, body=body).execute()

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
    from .clinic import get_clinic
    from .store import Store

    cal = get_calendar()
    if not cal:
        raise SystemExit(f"no service account key at {settings.GOOGLE_SERVICE_ACCOUNT_FILE}")
    if not settings.BOOKING_CALENDAR_SHARE_WITH:
        raise SystemExit("set BOOKING_CALENDAR_SHARE_WITH in .env")
    store, clinic = Store(settings.DB_PATH), get_clinic()
    print(f"service account: {cal.email}")
    calendar_id = ensure_calendar(store, cal, clinic.id, f"{clinic.name('mn')} · цаг захиалга")
    print(f"- {clinic.id}: {calendar_id}\n  shared with {settings.BOOKING_CALENDAR_SHARE_WITH}")


def cmd_status(args):
    from .clinic import get_clinic
    from .store import Store

    cal = get_calendar()
    if not cal:
        raise SystemExit(f"no service account key at {settings.GOOGLE_SERVICE_ACCOUNT_FILE}")
    print(f"service account: {cal.email}")
    clinic = get_clinic()
    calendar_id = Store(settings.DB_PATH).get_calendar_id(clinic.id)
    if not calendar_id:
        raise SystemExit("no calendar linked yet: run python -m app.gcal setup")
    with cal._lock:
        meta = cal.api.calendars().get(calendarId=calendar_id).execute()
    print(f"- {clinic.id}: OK '{meta['summary']}' ({meta['timeZone']})")


def main():
    parser = argparse.ArgumentParser(prog="python -m app.gcal")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup", help="create and share the booking calendar").set_defaults(func=cmd_setup)
    sub.add_parser("status", help="check calendar access").set_defaults(func=cmd_status)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
