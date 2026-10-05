"""bas.mn sync against an in-memory fake of their API (quirks included: empty
lists answer 404, a created event comes back without an id)."""
import json
import re
import time
from datetime import datetime, timedelta
from urllib.parse import unquote

import httpx
import pytest

from app import basmn, crm, meetings
from app.config import settings
from app.pricing import Pricing
from app.store import Store

TZ = crm._tz()


class FakeBas:
    def __init__(self):
        self.leads, self.events, self.items = {}, {}, []
        self.calls, self.fail_next = [], 0

    def __call__(self, method, url, headers=None, json=None, **kw):
        path = url.split("/api", 1)[1]
        self.calls.append((method, path, json))
        assert headers["authtoken"] == "test-key"
        if self.fail_next:
            self.fail_next -= 1
            return httpx.Response(500, text="boom")
        body = self.route(method, unquote(path), json or {})
        if body is None:
            return httpx.Response(404, json={"status": False, "message": "No data were found"})
        return httpx.Response(200, json=body)

    def route(self, method, path, data):
        if path == "/staffs/search/a":
            return [{"staffid": "1", "firstname": "M", "lastname": "A", "email": "m@a"}]
        if path == "/items":
            return self.items or None
        if path == "/leads" and method == "GET":
            return list(self.leads.values()) or None
        if path == "/leads" and method == "POST":
            lead_id = str(len(self.leads) + 1)
            self.leads[lead_id] = {"id": lead_id, **data}
            return {"status": True, "record_id": int(lead_id)}
        m = re.fullmatch(r"/leads/search/(.+)", path)
        if m:
            hits = [l for l in self.leads.values() if m.group(1) in str(l.get("phonenumber", ""))]
            return hits or None
        m = re.fullmatch(r"/leads/(\d+)", path)
        if m:
            lead = self.leads.get(m.group(1))
            if lead and method == "PUT":
                lead.update(data)
                return {"status": True}
            return lead
        if path == "/calendar" and method == "GET":
            return [{"eventid": k, "userid": "1", **v} for k, v in self.events.items()] or None
        if path == "/calendar" and method == "POST":
            missing = {"reminder_before", "reminder_before_type", "isstartnotified", "public"} - set(data)
            assert not missing, missing
            self.events[str(len(self.events) + 100)] = dict(data)
            return {"status": True}
        m = re.fullmatch(r"/calendar/(\d+)", path)
        if m and method == "PUT":
            self.events[m.group(1)].update(data)
            return {"status": True}
        if m and method == "DELETE":
            return {"status": True} if self.events.pop(m.group(1), None) else None
        raise AssertionError(f"unexpected {method} {path}")


@pytest.fixture
def fake(monkeypatch, tmp_path):
    bas = FakeBas()
    monkeypatch.setattr(basmn.httpx, "request", bas)
    monkeypatch.setattr(settings, "BASMN_URL", "https://crm.test")
    monkeypatch.setattr(settings, "BASMN_API_KEY", "test-key")
    monkeypatch.setattr(settings, "SERVERLESS", False)
    return bas


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "t.db"))


def _when(days=2, hour=11):
    d = datetime.now(TZ).replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=days)
    return d, d + timedelta(minutes=45)


def _booking(store, business="ajilt_ai", phone="99112233", name="Бат", channel="messenger"):
    start, end = _when()
    return store.save_booking({
        "business_id": business, "sender_id": "s1", "channel": channel, "service_id": "demo_meeting",
        "start_at": start.isoformat(), "end_at": end.isoformat(), "name": name, "phone": phone,
        "status": "no_calendar"})


def _run(store):
    total = {"sent": 0, "retry": 0, "failed": 0}
    while True:
        r = crm.flush(store)
        for k in total:
            total[k] += r[k]
        if not r["sent"]:
            return total


def test_nothing_is_queued_without_a_key(store, monkeypatch):
    monkeypatch.setattr(settings, "BASMN_API_KEY", "")
    crm.enqueue(store, "booking", 1)
    assert store.crm_counts() == {}


def test_own_meeting_then_sales_lead_is_one_lead_and_a_linked_event(store, fake):
    bid = _booking(store)
    crm.enqueue(store, "booking", bid, {"business": "Ажилт-AI", "service": "Ажилт-AI уулзалт"})

    class S:  # what conversation.save_lead stores for the same person
        sender_id, channel = "s1", "messenger"
        data = {"org_name": "Номин ХХК", "business_type": "Retail", "employees": 20, "branches": 2,
                "tier": "PRO", "quote": 1000000, "phone": "99112233", "contact_name": "Бат"}
    lid = store.save_lead(S, path="booking")
    crm.enqueue(store, "lead", lid, {"interest": "Уулзалт товлосон"})
    assert _run(store) == {"sent": 2, "retry": 0, "failed": 0}

    assert len(fake.leads) == 1
    lead = fake.leads["1"]
    assert lead["status"] == 2 and lead["source"] == 2 and lead["assigned"] == 1
    assert lead["company"] == "Номин ХХК" and lead["lead_value"] == 1000000
    assert "Messenger" in lead["tags"] and "demo" not in lead["tags"]
    assert "Үнийн санал: 1,000,000₮/сар" in lead["description"]

    (event,) = fake.events.values()
    assert event["title"] == "Ажилт-AI уулзалт — Бат"
    assert event["color"] == crm.COLORS["chatbot"]
    assert "https://crm.test/admin/leads/index/1" in event["description"]
    row = store.get_row("bookings", bid)
    assert row["crm_lead_id"] == "1" and row["crm_event_id"] == "100"
    assert store.get_row("leads", lid)["crm_lead_id"] == "1"


def test_demo_booking_is_marked(store, fake):
    bid = _booking(store, business="dental", channel="instagram")
    crm.enqueue(store, "booking", bid, {"business": "Mayflower", "service": "Үзлэг", "staff": "Дорж"})
    _run(store)
    (event,) = fake.events.values()
    assert event["title"].startswith("[DEMO] Mayflower: Үзлэг — Бат")
    assert event["color"] == crm.COLORS["demo"]
    lead = fake.leads["1"]
    assert "demo" in lead["tags"] and "Instagram" in lead["tags"]
    assert lead["source"] == settings.BASMN_SOURCE_FACEBOOK     # no Instagram source set


def test_failures_are_retried_not_lost(store, fake):
    bid = _booking(store)
    fake.fail_next = 1
    crm.enqueue(store, "booking", bid, {"service": "Уулзалт"})
    assert crm.flush(store) == {"sent": 0, "retry": 1, "failed": 0}
    (job,) = store.crm_jobs()
    assert job["status"] == "pending" and job["attempts"] == 1 and "500" in job["last_error"]
    with store._conn() as c:      # pretend the backoff has passed
        c.execute("UPDATE crm_outbox SET next_try = ?", (time.time() - 1,))
    assert crm.flush(store)["sent"] == 1
    assert len(fake.events) == 1


def test_a_retry_does_not_duplicate(store, fake):
    bid = _booking(store)
    crm.enqueue(store, "booking", bid, {"service": "Уулзалт"})
    _run(store)
    store.set_crm_ids("bookings", bid, crm_event_id="")      # as if the id was lost mid-way
    crm.enqueue(store, "booking", bid, {"service": "Уулзалт"})
    _run(store)
    assert len(fake.events) == 1 and len(fake.leads) == 1


def test_meeting_status_marks_and_cancels(store, fake):
    bid = _booking(store)
    crm.enqueue(store, "booking", bid, {"service": "Уулзалт"})
    crm.enqueue(store, "meeting_status", bid, {"table": "bookings", "status": "confirmed"})
    _run(store)
    assert fake.events["100"]["title"] == "✅ Уулзалт — Бат"

    crm.enqueue(store, "meeting_status", bid, {"table": "bookings", "status": "cancelled"})
    _run(store)
    assert fake.events == {}
    assert store.get_row("bookings", bid)["crm_event_id"] == ""
    assert "Уулзалт цуцлагдсан" in fake.leads["1"]["description"]

    crm.enqueue(store, "meeting_status", bid, {"table": "bookings", "status": "new"})
    _run(store)
    assert [e["title"] for e in fake.events.values()] == ["Уулзалт — Бат"]


def test_status_waits_for_its_booking(store, fake):
    bid = _booking(store)
    fake.fail_next = 1
    crm.enqueue(store, "booking", bid, {"service": "Уулзалт"})
    crm.enqueue(store, "meeting_status", bid, {"table": "bookings", "status": "confirmed"})
    r = crm.flush(store)
    assert r["sent"] == 0 and r["retry"] == 2


def test_website_booking(store, fake):
    start, _ = _when(days=3, hour=14)
    row = meetings.create(store, None, {
        "type": "online", "date": f"{start:%Y-%m-%d}", "time": "14:00", "name": "Сараа",
        "phone": "8811-2233", "email": "s@x.mn", "business": "Сараа салон", "plan": "PRO"})
    _run(store)
    lead = fake.leads["1"]
    assert lead["source"] == settings.BASMN_SOURCE_WEBSITE and lead["email"] == "s@x.mn"
    (event,) = fake.events.values()
    assert event["title"] == "Онлайн уулзалт — Сараа (вэб)" and event["color"] == crm.COLORS["website"]
    assert store.get_row("site_bookings", row["id"])["crm_event_id"] == "100"


def test_pull_cancels_moves_and_reads_prices(store, fake):
    keep, gone = _booking(store, phone="99000001"), _booking(store, phone="99000002", name="Дулам")
    for bid in (keep, gone):
        crm.enqueue(store, "booking", bid, {"service": "Уулзалт"})
    _run(store)
    moved_to = _when(days=4, hour=15)[0].replace(tzinfo=None)
    first, second = sorted(fake.events)
    fake.events[first]["start"] = f"{moved_to:%Y-%m-%d %H:%M:%S}"
    fake.events[first]["end"] = f"{moved_to + timedelta(minutes=45):%Y-%m-%d %H:%M:%S}"
    del fake.events[second]
    fake.events["900"] = {"title": "Staff typed this", "start": f"{moved_to:%Y-%m-%d} 10:00:00",
                          "end": f"{moved_to:%Y-%m-%d} 11:00:00"}
    fake.events["901"] = {"title": "[DEMO] x", "start": f"{moved_to:%Y-%m-%d} 12:00:00", "end": ""}
    fake.items = [{"description": "PRO багц", "rate": "900000.00"}, {"description": "Other", "rate": "0"}]

    report = crm.pull(store)
    assert report == {"events": 3, "cancelled": 1, "moved": 1, "prices": 1}
    assert store.get_row("bookings", gone)["meeting_status"] == "cancelled"
    assert crm._local(store.get_row("bookings", keep)["start_at"]) == moved_to

    day = moved_to.replace(hour=0, tzinfo=TZ)
    titles = {(s.hour, e.hour) for s, e, _ in crm.busy(store, day, day + timedelta(days=1))}
    assert (10, 11) in titles and (15, 15) in titles and all(s != 12 for s, _ in titles)

    pricing = Pricing(settings.PRICING_PATH, lambda: crm.prices(store))
    assert pricing.quote(20, 0, "Retail")[1] == 900000      # PRO from bas.mn
    assert pricing.quote(5, 0, "Retail")[1] == 500000       # STARTER from pricing.yaml


def test_order_and_its_status(store, fake):
    rid = store.save_request({"business_id": "wholesale", "sender_id": "s", "channel": "web",
                              "title": "Бөөний захиалга", "details": ["Гурил × 10"],
                              "name": "Болд", "phone": "95112233"})
    crm.enqueue(store, "order", rid, {"business": "MCC Foods", "demo": True})
    store.set_request_status("wholesale", rid, "delivered")
    crm.enqueue(store, "order_status", rid, {"status": "delivered"})
    _run(store)
    desc = fake.leads["1"]["description"]
    assert "Гурил × 10" in desc and f"Захиалга #{rid}: хүргэгдсэн" in desc
    assert "demo" in fake.leads["1"]["tags"]


def test_bad_job_is_parked_as_failed(store, fake):
    store.crm_enqueue("nonsense", 1)
    assert crm.flush(store)["failed"] == 1
    assert crm.status(store)["failed"][0]["kind"] == "nonsense"
    assert store.crm_requeue_failed() == 1


def test_fix_old_leads_only_touches_chatbot_leads(fake):
    fake.leads = {
        "7": {"id": "7", "name": "Бат", "source": "1", "status": "1",
              "description": "Уулзалт товлосон\nСуваг: Instagram\nАжилт-AI чатботоор бүртгэгдсэн."},
        "8": {"id": "8", "name": "Real customer", "source": "1", "status": "1", "description": "x"},
    }
    bas = basmn.BasMN()
    dry = crm.fix_old_leads(bas)
    assert dry[0].startswith("lead 7") and fake.leads["7"]["status"] == "1"
    crm.fix_old_leads(bas, apply=True)
    assert fake.leads["7"]["status"] == 2 and fake.leads["7"]["source"] == 2
    assert fake.leads["8"]["status"] == "1"
