"""The clinic website's booking form: /api/catalog, /api/slots, /api/bookings.

    python -m pytest tests
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import crm, main
from app.clinic import get_clinic
from app.store import Store

from test_crm import FakeBas

TOKEN = {"X-Booking-Token": "form-s3cret"}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(crm, "configured", lambda: True)     # queue jobs; nothing is sent by itself
    s = Store(str(tmp_path / "test.db"))
    monkeypatch.setattr(main, "store", s)
    monkeypatch.setattr(main.engine.booking, "store", s)
    monkeypatch.setattr(main.settings, "WEB_BOOKING_TOKEN", "form-s3cret")
    return s


@pytest.fixture
def client(store):
    return TestClient(main.app)


def open_day(client, branch="kr_gangnam", service="excel_v"):
    """The first day ahead with free slots, and those slots."""
    tz = ZoneInfo(get_clinic().country_of(get_clinic().branch(branch))["tz"])
    for offset in range(1, 10):
        day = (datetime.now(tz) + timedelta(days=offset)).strftime("%Y-%m-%d")
        slots = client.get("/api/slots", params={"branch": branch, "service": service, "date": day}).json()["slots"]
        if slots:
            return day, slots
    raise AssertionError("no open day in the next 9 days")


def form(day, time, **kw):
    return {"name": "Б. Хулан", "phone": "010-1111-2222", "branch": "kr_gangnam", "service": "excel_v",
            "date": day, "time": time, "lang": "ko", **kw}


def test_catalog_lists_branches_and_prices(client):
    r = client.get("/api/catalog")
    data = r.json()
    clinic = get_clinic()
    assert r.status_code == 200 and "max-age" in r.headers["cache-control"]
    assert [b["id"] for b in data["branches"]] == [b["id"] for b in clinic.branches]
    service = next(s for s in data["services"] if s["id"] == "excel_v")
    assert set(service["price"]) == {"MNT", "KRW"} and service["minutes"] > 0
    assert set(data["branches"][0]) <= {"id", "country", "name", "address", "hours_text", "note"}


def test_slots_check_their_input(client):
    assert client.get("/api/slots", params={"branch": "nope", "service": "excel_v", "date": "2026-01-01"}).status_code == 400
    assert client.get("/api/slots", params={"branch": "kr_gangnam", "service": "excel_v", "date": "1.1"}).status_code == 400
    past = client.get("/api/slots", params={"branch": "kr_gangnam", "service": "excel_v", "date": "2020-01-01"})
    assert past.status_code == 200 and past.json()["slots"] == []


def test_booking_needs_the_token(client, monkeypatch):
    day, slots = open_day(client)
    assert client.post("/api/bookings", json=form(day, slots[0]), headers={"X-Booking-Token": "x"}).status_code == 403
    monkeypatch.setattr(main.settings, "WEB_BOOKING_TOKEN", "")
    assert client.post("/api/bookings", json=form(day, slots[0]), headers=TOKEN).status_code == 503


def test_form_booking_is_saved_queued_and_takes_the_slot(client, store):
    day, slots = open_day(client)
    r = client.post("/api/bookings", headers=TOKEN,
                    json=form(day, slots[0], email="hulan@example.com", note="оройн цаг"))
    assert r.status_code == 201
    booking = store.get_booking(r.json()["id"])
    assert booking["channel"] == "website" and booking["lang"] == "ko"
    assert booking["note"] == "hulan@example.com · оройн цаг"
    assert booking["start_at"].startswith(f"{day}T{slots[0]}")

    bas = FakeBas()                                           # the queued job reaches bas.mn
    crm.flush(store, bas=bas, clinic=get_clinic())
    assert "Тэмдэглэл: hulan@example.com · оройн цаг" in bas.events_rows[0]["description"]

    capacity = get_clinic().branch("kr_gangnam")["capacity"]
    for _ in range(capacity - 1):
        assert client.post("/api/bookings", headers=TOKEN, json=form(day, slots[0])).status_code == 201
    left = client.get("/api/slots", params={"branch": "kr_gangnam", "service": "excel_v", "date": day}).json()["slots"]
    assert slots[0] not in left
    assert client.post("/api/bookings", headers=TOKEN, json=form(day, slots[0])).status_code == 409


def test_form_booking_checks_its_input(client):
    day, slots = open_day(client)
    assert client.post("/api/bookings", headers=TOKEN, json=form(day, slots[0], phone="123")).status_code == 400
    assert client.post("/api/bookings", headers=TOKEN, json=form(day, slots[0], name=" ")).status_code == 400
    assert client.post("/api/bookings", headers=TOKEN, json=form(day, "03:17")).status_code == 409
    assert client.post("/api/bookings", headers=TOKEN, json=form(day, slots[0], service="nope")).status_code == 400
