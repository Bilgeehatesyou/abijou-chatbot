"""chatbot <-> bas.mn sync against a fake bas.mn that behaves like the real one:
creates of invoices and events return no id, invoices are found by number, and so on.

    python -m pytest tests
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import crm
from app.basmn import BasError
from app.booking import BookingFlow, free_slots
from app.clinic import get_clinic
from app.store import Store


class FakeBas:
    url = "https://clinic.bas.mn"

    def __init__(self):
        self.customers_rows, self.events_rows, self.invoices = [], [], {}
        self.fields = {"customers": {"Салбар": 1, "Хэл": 2, "Суваг": 3},
                       "invoice": {"Салбар": 4, "Захиалгын дугаар": 5}}
        self.fail_customer = False

    def custom_fields(self, kind):
        return self.fields[kind]

    def customers(self):
        return list(self.customers_rows)

    def create_customer(self, fields):
        if self.fail_customer:
            raise BasError("bas.mn redirected to /admin/ (a plan limit)")
        cid = str(len(self.customers_rows) + 1)
        self.customers_rows.append({"userid": cid, "phonenumber": fields["phonenumber"], **fields})
        return cid

    def events(self):
        return [dict(e) for e in self.events_rows]

    def find_event(self, title, start):
        when = start.strftime("%Y-%m-%d %H:%M")
        return next((e["id"] for e in self.events_rows if e["title"] == title and e["start"].startswith(when)), None)

    def create_event(self, *, title, start, end, description, color, staff_id=1):
        self.events_rows.append({"id": str(len(self.events_rows) + 100), "title": title, "description": description,
                                 "start": start.strftime("%Y-%m-%d %H:%M:%S"), "end": end.strftime("%Y-%m-%d %H:%M:%S"),
                                 "color": color, "userid": staff_id})
        return self.find_event(title, start)

    def update_event(self, event, **fields):
        row = next(e for e in self.events_rows if e["id"] == event["id"])
        row.update(fields)

    def invoice(self, invoice_id):
        return self.invoices.get(str(invoice_id))

    def create_invoice(self, data):
        iid = str(len(self.invoices) + 1)
        self.invoices[iid] = {"id": iid, "hash": "h" + iid, "status": "1", **data}
        return self.invoices[iid]

    def last_invoice_number(self):
        return max((int(i["number"]) for i in self.invoices.values()), default=0)

    def invoice_link(self, invoice):
        return f"{self.url}/invoice/{invoice['id']}/{invoice['hash']}"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(crm, "configured", lambda: True)     # queue jobs; nothing is sent by itself
    return Store(str(tmp_path / "test.db"))


@pytest.fixture
def bas():
    return FakeBas()


def book(store, branch="kr_gangnam", service="excel_v", phone="010-1111-2222", name="Б. Хулан",
         day_offset=2, hour=14, channel="instagram", lang="mn"):
    clinic = get_clinic()
    b, s = clinic.branch(branch), clinic.service(service)
    country = clinic.country_of(b)
    tz = ZoneInfo(country["tz"])
    start = (datetime.now(tz) + timedelta(days=day_offset)).replace(hour=hour, minute=0, second=0, microsecond=0)
    row = {"sender_id": "u1", "channel": channel, "lang": lang, "service_id": service, "branch_id": branch,
           "country": b["country"], "start_at": start.isoformat(),
           "end_at": (start + timedelta(minutes=s["minutes"])).isoformat(), "name": name, "phone": phone,
           "price": s["price"][country["currency"]], "currency": country["currency"], "event_id": None,
           "calendar_status": "no_calendar"}
    bid = store.save_booking(row)
    crm.enqueue(store, "booking", bid)
    return bid


def run(store, bas):
    return crm.flush(store, bas=bas, clinic=get_clinic())


def test_booking_becomes_patient_and_appointment(store, bas):
    bid = book(store)
    assert run(store, bas)["sent"] == 1
    b = store.get_booking(bid)
    assert b["crm_customer_id"] == "1" and b["crm_event_id"]
    customer = bas.customers_rows[0]
    assert customer["company"] == "Б. Хулан" and customer["country"] == 207
    assert customer["custom_fields[customers][1]"] == "Сөүл · Каннам"
    assert customer["custom_fields[customers][2]"] == "Монгол"
    assert customer["custom_fields[customers][3]"] == "Instagram"
    event = bas.events_rows[0]
    assert event["title"] == "Каннам · Excel-V лазер · Б. Хулан"
    assert event["start"].endswith("14:00:00")              # the branch's own time
    assert event["color"] == "#3B82F6" and "BK-" in event["description"]


def test_same_phone_reuses_the_patient(store, bas):
    book(store, phone="010-1111-2222")
    book(store, phone="+82 10 1111 2222", day_offset=3, service="rejuran")
    run(store, bas)
    assert len(bas.customers_rows) == 1 and len(bas.events_rows) == 2


def test_known_customer_in_bas_is_found_by_phone(store, bas):
    bas.customers_rows.append({"userid": "77", "phonenumber": "99112233", "company": "Old patient"})
    bid = book(store, branch="ub_central", phone="9911-2233")
    run(store, bas)
    assert store.get_booking(bid)["crm_customer_id"] == "77" and len(bas.customers_rows) == 1


def test_came_makes_the_invoice(store, bas):
    bid = book(store)
    run(store, bas)
    store.update_booking(bid, status="done")
    crm.enqueue(store, "status", bid, {"status": "done"})
    run(store, bas)
    b = store.get_booking(bid)
    inv = bas.invoices[b["crm_invoice_id"]]
    assert inv["currency"] == 5 and inv["total"] == "120000.00"           # KRW
    assert [inv[f"allowed_payment_modes[{i}]"] for i in range(3)] == [1, 2, 3]   # no QPay in Korea
    assert inv["newitems[0][description]"].startswith("🇰🇷 Excel-V")
    assert inv["custom_fields[invoice][4]"] == "Сөүл · Каннам"
    assert inv["custom_fields[invoice][5]"].startswith("BK-")
    assert b["crm_invoice_number"] == "900001" and b["payment_status"] == "unpaid"
    assert b["payment_link"] == "https://clinic.bas.mn/invoice/1/h1"
    assert bas.events_rows[0]["color"] == "#10B981"                   # came: green


def test_invoice_numbers_follow_the_bots_last_one(store, bas):
    bas.invoices["9"] = {"id": "9", "number": "900041", "hash": "x", "status": "2"}
    bid = book(store, branch="ub_zaisan", service="neobeam", phone="88001122")
    run(store, bas)
    store.update_booking(bid, status="done")
    crm.enqueue(store, "status", bid)
    run(store, bas)
    b = store.get_booking(bid)
    assert b["crm_invoice_number"] == "900042"
    assert bas.invoices[b["crm_invoice_id"]]["currency"] == 3                # MNT


def test_staff_invoice_numbers_are_left_alone(store, bas):
    bas.invoices["9"] = {"id": "9", "number": "41", "hash": "x", "status": "2"}    # made by staff
    bid = book(store)
    run(store, bas)
    crm.enqueue(store, "status", bid, {"status": "done"})
    run(store, bas)
    assert store.get_booking(bid)["crm_invoice_number"] == "900001"


def test_free_consultation_gets_no_invoice(store, bas):
    bid = book(store, service="consult")                     # free in Korea
    run(store, bas)
    crm.enqueue(store, "status", bid, {"status": "done"})
    run(store, bas)
    assert not bas.invoices and not store.get_booking(bid)["crm_invoice_id"]


def test_cancel_marks_the_appointment(store, bas):
    bid = book(store)
    run(store, bas)
    crm.enqueue(store, "status", bid, {"status": "cancelled"})
    run(store, bas)
    assert bas.events_rows[0]["color"] == "#9CA3AF"


def test_pull_reads_staff_changes(store, bas):
    deleted, came, moved = book(store, phone="010-1"), book(store, phone="010-2", hour=15), \
        book(store, phone="010-3", hour=16)
    run(store, bas)
    ev = {store.get_booking(b)["crm_event_id"]: b for b in (deleted, came, moved)}
    bas.events_rows = [e for e in bas.events_rows if ev[e["id"]] != deleted]
    for e in bas.events_rows:
        if ev[e["id"]] == came:
            e["title"] = "ИРСЭН " + e["title"]
        if ev[e["id"]] == moved:
            e["start"] = e["start"][:11] + "18:30:00"
            e["end"] = e["start"][:11] + "19:00:00"
    changes = crm.pull(store, bas=bas, clinic=get_clinic())
    assert changes == {"cancelled": 1, "came": 1, "moved": 1, "paid": 0}
    assert store.get_booking(deleted)["status"] == "cancelled"
    assert store.get_booking(moved)["start_at"][11:16] == "18:30" and store.get_booking(moved)["start_at"].endswith("+09:00")
    run(store, bas)                                          # "came" queued the invoice
    b = store.get_booking(came)
    assert b["status"] == "done" and b["crm_invoice_id"]
    bas.invoices[b["crm_invoice_id"]]["status"] = "2"         # paid at the counter
    assert crm.pull(store, bas=bas, clinic=get_clinic())["paid"] == 1
    assert store.get_booking(came)["payment_status"] == "paid"


def test_staff_appointments_block_chatbot_slots(store, bas):
    clinic = get_clinic()
    branch = clinic.branch("ub_central")
    tz = ZoneInfo("Asia/Ulaanbaatar")
    day = (datetime.now(tz) + timedelta(days=3)).date()
    while not branch["hours"].get(["mon", "tue", "wed", "thu", "fri", "sat", "sun"][day.weekday()]):
        day += timedelta(days=1)
    start = datetime.combine(day, datetime.strptime("12:00", "%H:%M").time())
    for i in range(branch["capacity"]):               # the whole branch is busy 12:00-13:00
        bas.events_rows.append({"id": f"s{i}", "title": f"Утсаар · Төв · patient {i}", "description": "",
                                "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                                "end": (start + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
                                "color": "", "userid": 1})
    crm.pull(store, bas=bas, clinic=clinic)
    flow = BookingFlow(store, clinic)
    window = datetime.combine(day, datetime.min.time(), tz)
    busy = flow._busy(branch, window, window + timedelta(days=1))
    slots = free_slots(branch["hours"], day, 30, busy, datetime.now(tz), tz, branch["capacity"])
    assert start.replace(tzinfo=tz) not in slots
    assert start.replace(tzinfo=tz) + timedelta(hours=1) in slots


def test_failures_are_retried_not_lost(store, bas):
    bas.fail_customer = True
    bid = book(store)
    result = run(store, bas)
    assert result["retry"] == 1 and store.crm_counts() == {"pending": 1}
    assert "plan limit" in store.crm_jobs()[0]["last_error"]
    assert store.get_booking(bid)["crm_event_id"] is None


def test_warns_as_customers_near_the_plan_cap(store, bas, capsys):
    bas.customers_rows = [{"userid": str(i), "phonenumber": f"8800{i:04d}"} for i in range(79)]
    crm.pull(store, bas=bas, clinic=get_clinic())
    assert "WARNING" not in capsys.readouterr().out
    book(store, phone="99112233")
    run(store, bas)                                          # the 80th customer
    assert store.crm_state_get("customer_count") == 80
    assert "80 of its 100 customers" in capsys.readouterr().out


def test_sync_endpoint_needs_its_token_then_pulls(store, bas, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(crm, "_client", lambda: bas)
    client = TestClient(main.app)
    monkeypatch.setattr(main.settings, "BASMN_SYNC_TOKEN", "")
    assert client.post("/api/basmn/sync").status_code == 503
    monkeypatch.setattr(main.settings, "BASMN_SYNC_TOKEN", "s3cret")
    assert client.post("/api/basmn/sync", headers={"X-Sync-Token": "wrong"}).status_code == 403

    bid = book(store)                                        # queued, not sent yet
    bas.events_rows.clear()
    r = client.post("/api/basmn/sync", headers={"X-Sync-Token": "s3cret"})
    assert r.status_code == 200 and r.json()["sent"]["sent"] == 1
    assert store.get_booking(bid)["crm_event_id"]
    bas.events_rows.clear()                                  # staff delete it in bas.mn
    r = client.post("/api/basmn/sync", headers={"X-Sync-Token": "s3cret"})
    assert r.json()["changes"]["cancelled"] == 1 and store.get_booking(bid)["status"] == "cancelled"
