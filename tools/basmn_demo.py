"""A month of made-up clinic activity in bas.mn, for demos — and its removal.

    python -m tools.basmn_demo plan               # what would be created (no API calls)
    python -m tools.basmn_demo generate           # create it (asks bas.mn ~600 times, ~5 min)
    python -m tools.basmn_demo addresses          # add home addresses to data made without them
    python -m tools.basmn_demo redo-invoices      # delete and remake the invoices and payments
    python -m tools.basmn_demo delete             # remove everything it created

What it makes, from data/clinic.yaml (treatments, prices, branches):
  - patients (bas.mn customers) with branch / language / channel custom fields
  - one calendar appointment per booking: done, cancelled, no-show or upcoming
  - an invoice for every visit, in ₮ (Mongolia) or ₩ (Korea), with the branch
  - payments: QPay / card / bank transfer / cash; a few unpaid or partly paid

Everything is recorded in basmn_demo.json (ids) and marked "DEMO DATA" in the
invoice admin note and the appointment description, so `delete` finds it all.
Invoices are deleted newest first: bas.mn only allows deleting the last invoice.
"""
import argparse
import json
import random
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from app.booking import WEEKDAY_KEYS, opening_hours
from app.clinic import get_clinic
from zoneinfo import ZoneInfo

MANIFEST = Path("basmn_demo.json")
MARK = "DEMO DATA"
SEED = 20261028
PAUSE = 0.75            # seconds between calls: the key allows a burst of 100, 1,000 an hour

# bas.mn ids on company1 (found by probing): currencies and payment modes
CURRENCY_ID = {"MNT": "3", "KRW": "5"}
MODE_ID = {"cash": "1", "bank": "2", "card": "3", "qpay": "4"}
MODE_NAME = {"cash": "Cash", "bank": "Bank Transfer", "qpay": "QPay", "card": "Card"}
PAY_MIX = {"mn": {"qpay": 45, "card": 30, "bank": 15, "cash": 10},
           "kr": {"card": 70, "cash": 20, "bank": 10}}
ALLOWED_MODES = {"mn": ["1", "2", "3", "4"], "kr": ["1", "2", "3"]}
CF = {"customer_branch": 1, "customer_lang": 2, "customer_channel": 3,
      "invoice_branch": 4, "invoice_booking": 5}

# bookings in the past 30 days per branch, and in the coming week
VOLUME = {"ub_central": 8, "ub_zaisan": 6, "ub_bayanzurkh": 5, "ub_sansar": 4,
          "kr_gangnam": 8, "kr_myeongdong": 5, "kr_sinsa": 3, "kr_hongdae": 3,
          "kr_jamsil": 3, "kr_incheon": 2, "kr_busan": 2, "kr_daegu": 2}
UPCOMING_SHARE = 0.15
TREATMENT_MIX = {"consult": 8, "acne_package": 14, "neobeam": 12, "gold_ptt": 9, "select_acne": 8,
                 "acne_scar": 6, "excel_v": 10, "rejuran": 8, "pico_toning": 9, "lifting": 5,
                 "botox_filler": 7, "aqua_peel": 8}
COLORS = {"upcoming": "#3B82F6", "done": "#10B981", "cancelled": "#9CA3AF", "no_show": "#9CA3AF"}
COUNTRY_ID = {"mn": "146", "kr": "207"}         # bas.mn's country list: Mongolia, South Korea

# made-up home addresses near each branch: (district, postcode prefix)
UB_DISTRICTS = {"ub_central": ["Сүхбаатар", "Чингэлтэй", "Баянгол"], "ub_zaisan": ["Хан-Уул", "Баянгол"],
                "ub_bayanzurkh": ["Баянзүрх", "Сүхбаатар"], "ub_sansar": ["Баянзүрх", "Чингэлтэй"]}
UB_ZIP = {"Сүхбаатар": "14", "Чингэлтэй": "15", "Баянгол": "16", "Хан-Уул": "17", "Баянзүрх": "13"}
KR_AREAS = {"kr_gangnam": ("서울특별시", [("강남구", "06"), ("서초구", "06")]),
            "kr_sinsa": ("서울특별시", [("강남구", "06"), ("서초구", "06")]),
            "kr_myeongdong": ("서울특별시", [("중구", "04"), ("용산구", "04"), ("동대문구", "02")]),
            "kr_hongdae": ("서울특별시", [("마포구", "04"), ("서대문구", "03")]),
            "kr_jamsil": ("서울특별시", [("송파구", "05"), ("광진구", "05")]),
            "kr_incheon": ("인천광역시", [("부평구", "21"), ("남동구", "21")]),
            "kr_busan": ("부산광역시", [("부산진구", "47"), ("해운대구", "48")]),
            "kr_daegu": ("대구광역시", [("중구", "41"), ("수성구", "42")])}
KR_ROADS = {"서울특별시": ["테헤란로", "도산대로", "월드컵로", "올림픽로", "양화로", "한강대로", "퇴계로"],
            "인천광역시": ["부평대로", "경인로", "인주대로"], "부산광역시": ["중앙대로", "서면로", "해운대로"],
            "대구광역시": ["동성로", "달구벌대로", "국채보상로"]}

MN_FIRST = ["Анужин", "Номин", "Солонго", "Туул", "Оюунчимэг", "Энхжин", "Хулан", "Саруул", "Тэмүүлэн",
            "Мөнхзул", "Ариунаа", "Уянга", "Болормаа", "Дөлгөөн", "Марал", "Наранцэцэг", "Индра",
            "Гэрэлмаа", "Сарнай", "Мишээл", "Ану", "Цэлмэг", "Билгүүн", "Тэмүүжин", "Бат-Эрдэнэ",
            "Ганбаатар", "Хонгор", "Энх-Амгалан", "Золжаргал", "Нандин", "Одгэрэл", "Ундрах", "Есүй",
            "Хүслэн", "Ирмүүн", "Сувд", "Амин-Эрдэнэ", "Батзаяа", "Хэрлэн", "Оргил"]
MN_INITIAL = list("БГДЭМНОСТХЦЧ")
KO_FAMILY = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임", "한", "오", "서", "신", "권", "황"]
KO_GIVEN = ["지은", "서연", "민지", "유진", "하은", "수빈", "예린", "지아", "민서", "채원", "소희", "지현",
            "다은", "예은", "나연", "지민", "서윤", "하린", "수아", "민준", "도윤", "서준", "현우", "지호"]
CHANNELS = {"Instagram": 55, "Facebook": 30, "Вэб чат": 15}


def pick(weights: dict, rng):
    return rng.choices(list(weights), weights=list(weights.values()))[0]


# ---------- planning (no API) ----------
def make_plan(today: date) -> dict:
    """Everything to create, decided up front from a fixed seed (same plan every time)."""
    rng = random.Random(SEED)
    clinic = get_clinic()
    patients, bookings = [], []
    used_names = set()

    def new_patient(branch):
        country = branch["country"]
        korean = country == "kr" and rng.random() < 0.3        # most patients in Korea are Mongolian
        for _ in range(200):   # 16x24 Korean and 12x40 Mongolian combinations: plenty, but bounded
            name = (rng.choice(KO_FAMILY) + rng.choice(KO_GIVEN) if korean
                    else f"{rng.choice(MN_INITIAL)}. {rng.choice(MN_FIRST)}")
            if name not in used_names:
                break
        used_names.add(name)
        phone = (f"010-{rng.randint(2000, 9899)}-{rng.randint(1000, 9999)}" if country == "kr" and rng.random() < 0.7
                 else f"{rng.choice(['88', '99', '95', '94', '80', '86'])}{rng.randint(100000, 999999)}")
        p = {"key": f"p{len(patients) + 1}", "name": name, "phone": phone, "branch": branch["id"],
             "lang": "한국어" if korean else rng.choices(["Монгол", "English"], [95, 5])[0],
             "channel": pick(CHANNELS, rng)}
        patients.append(p)
        return p

    for branch in clinic.branches:
        tz = ZoneInfo(clinic.country_of(branch)["tz"])
        total = VOLUME[branch["id"]]
        upcoming = max(1, round(total * UPCOMING_SHARE))
        branch_patients = []
        for i in range(total + upcoming):
            future = i >= total
            for _ in range(50):     # a day the branch is open
                offset = rng.randint(0, 6) if future else -rng.randint(1, 30)
                day = today + timedelta(days=offset)
                if branch["hours"].get(WEEKDAY_KEYS[day.weekday()]):
                    break
            open_at, close_at = opening_hours(branch["hours"], day, tz)
            service = clinic.service(pick(TREATMENT_MIX, rng))
            slots = int((close_at - open_at).total_seconds() // 1800) - service["minutes"] // 30
            start = open_at + timedelta(minutes=30 * rng.randint(0, max(slots, 0)))
            # returning patients: a later session of the same course
            if branch_patients and rng.random() < 0.15:
                patient = rng.choice(branch_patients)
            else:
                patient = new_patient(branch)
                branch_patients.append(patient)
            country = branch["country"]
            currency = clinic.countries[country]["currency"]
            lines = _lines(service, currency, rng)
            if service["category"] in ("acne", "redness") and rng.random() < 0.18:
                rejuran = clinic.service("rejuran")["options"][0]     # the same-day booster offer
                lines.append({"description": _item_name(rejuran["name"], country),
                              "rate": round(rejuran[currency] * 0.9), "note": "10% хөнгөлөлт (лазертай хамт)"})
            outcome = "upcoming" if future else rng.choices(["done", "cancelled", "no_show"], [92, 5, 3])[0]
            payment = None
            if outcome == "done":
                status = rng.choices(["paid", "partial", "unpaid"], [90, 4, 6])[0]
                payment = {"status": status, "mode": pick(PAY_MIX[country], rng)}
            bookings.append({"key": f"b{len(bookings) + 1}", "patient": patient["key"], "branch": branch["id"],
                             "country": country, "currency": currency, "service": service["id"],
                             "start": start.isoformat(),
                             "end": (start + timedelta(minutes=service["minutes"])).isoformat(),
                             "outcome": outcome, "lines": lines, "payment": payment})
    bookings.sort(key=lambda b: b["start"])
    for n, b in enumerate(bookings, 1):
        b["ref"] = f"BK-{b['start'][:10].replace('-', '')}-{n:03d}"
    return {"patients": patients, "bookings": bookings}


def address_for(patient: dict) -> dict:
    """A made-up home address near the patient's branch. Seeded by the patient key, so it is
    the same on every run and doesn't change the rest of the plan."""
    rng = random.Random(f"{SEED}-{patient['key']}")
    branch = patient["branch"]
    if branch.startswith("ub_"):
        district = rng.choice(UB_DISTRICTS[branch])
        street = (f"{district} дүүрэг, {rng.randint(1, 26)}-р хороо, {rng.randint(1, 60)}-р байр, "
                  f"{rng.randint(1, 120)} тоот")
        return {"street": street, "city": "Улаанбаатар", "state": f"{district} дүүрэг",
                "zip": f"{UB_ZIP[district]}{rng.randint(100, 399)}", "country": COUNTRY_ID["mn"]}
    city, areas = KR_AREAS[branch]
    gu, zip_prefix = rng.choice(areas)
    street = (f"{gu} {rng.choice(KR_ROADS[city])}{rng.randint(1, 40)}길 {rng.randint(2, 99)}, "
              f"{rng.randint(1, 15)}0{rng.randint(1, 9)}호")
    return {"street": street, "city": city, "state": gu,
            "zip": f"{zip_prefix}{rng.randint(100, 999)}", "country": COUNTRY_ID["kr"]}


def address_fields(addr: dict, billing_only: bool = False) -> dict:
    fields = {f"billing_{k}": v for k, v in addr.items()}
    if not billing_only:
        fields.update({"address": addr["street"], "city": addr["city"], "state": addr["state"],
                       "zip": addr["zip"], "country": addr["country"]})
    return fields


def _item_name(name: dict, country: str) -> str:
    """Same wording as the bas.mn price list items."""
    return ("🇲🇳 " + name["mn"]) if country == "mn" else f"🇰🇷 {name['mn']} / {name['ko']}"


def _lines(service: dict, currency: str, rng) -> list:
    country = "mn" if currency == "MNT" else "kr"
    if service.get("options"):
        option = rng.choice([o for o in service["options"] if o.get(currency)])
        return [{"description": _item_name(option["name"], country), "rate": option[currency]}]
    label = _item_name(service["name"], country)
    packages = service.get("packages", [])
    if packages and rng.random() < 0.25:
        p = packages[0]
        return [{"description": f"{label} · {p['sessions']} удаагийн багц", "rate": p[currency]}]
    return [{"description": f"{label} · 1 удаа", "rate": service["price"][currency]}]


def summary(plan: dict):
    clinic = get_clinic()
    b = plan["bookings"]
    print(f"{len(plan['patients'])} patients, {len(b)} bookings "
          f"({sum(x['outcome'] == 'upcoming' for x in b)} upcoming)")
    for outcome in ("done", "cancelled", "no_show", "upcoming"):
        print(f"  {outcome:9} {sum(x['outcome'] == outcome for x in b)}")
    for cur in ("MNT", "KRW"):
        done = [x for x in b if x["outcome"] == "done" and x["currency"] == cur]
        billed = sum(l["rate"] for x in done for l in x["lines"])
        paid = sum(l["rate"] for x in done if x["payment"]["status"] == "paid" for l in x["lines"]) + \
            sum(sum(l["rate"] for l in x["lines"]) // 2 for x in done if x["payment"]["status"] == "partial")
        print(f"  {cur}: {len(done)} invoices, billed {billed:,}, paid {paid:,}")
    for branch in clinic.branches:
        n = sum(x["branch"] == branch["id"] for x in b)
        print(f"  {branch['name']['mn']:20} {n}")


# ---------- bas.mn ----------
class Bas:
    def __init__(self):
        env = dict(l.split("=", 1) for l in Path(".env").read_text(encoding="utf-8").splitlines()
                   if "=" in l and not l.lstrip().startswith("#"))
        self.base = env["BASMN_URL"].strip().rstrip("/") + "/api"
        self.headers = {"authtoken": env["BASMN_API_KEY"].strip()}
        self.calls = 0

    def call(self, method, path, **kw):
        time.sleep(PAUSE)
        self.calls += 1
        for attempt in range(6):
            r = httpx.request(method, self.base + path, headers=self.headers, timeout=40, **kw)
            # over the quota bas.mn answers 429. (A 303 to /admin/ is a plan cap, e.g. at
            # 100 customers on company1: retrying never helps, so it is returned as is.)
            if r.status_code != 429:
                break
            wait = 60 * (attempt + 1)
            print(f"  rate limited ({r.status_code}), waiting {wait}s", flush=True)
            time.sleep(wait)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, r.text[:200]

    def rows(self, path):
        out, page = [], 1
        while True:
            status, body = self.call("GET", path, params={"page": page})
            if status == 200 and isinstance(body, list):     # /payments isn't paged
                return out + body
            if status != 200 or not isinstance(body, dict):
                return out
            out += body.get("data", [])
            if page >= (body.get("meta") or {}).get("last_page", 1):
                return out
            page += 1


def save_manifest(m):
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")


def assign_patients(plan: dict, manifest: dict):
    """Bookings of patients bas.mn wouldn't take (its customer limit) become return visits
    of a patient at the same branch. Seeded, so every run assigns them the same way."""
    rng = random.Random(SEED + 1)
    created = [p for p in plan["patients"] if p["key"] in manifest["customers"]]
    patients = {p["key"]: p for p in plan["patients"]}
    for b in plan["bookings"]:
        if b["patient"] not in manifest["customers"]:
            same = [p for p in created if p["branch"] == b["branch"]] or created
            b["patient"] = rng.choice(same)["key"]
    plan["patients"] = [patients[k] for k in manifest["customers"]]


def make_invoice(bas: "Bas", manifest: dict, b: dict, patient: dict, number: int):
    """The visit's invoice and its payment. bas.mn dates every API payment today, whatever
    date is sent: only the invoice keeps the visit date."""
    branch = get_clinic().branch(b["branch"])
    start = datetime.fromisoformat(b["start"])
    total = sum(l["rate"] for l in b["lines"])
    unpaid = b["payment"]["status"] != "paid"
    due = start.date() + timedelta(days=7 if unpaid else 0)
    data = {"clientid": manifest["customers"][b["patient"]], "number": str(number),
            "date": start.date().isoformat(), "duedate": due.isoformat(),
            "currency": CURRENCY_ID[b["currency"]],
            "subtotal": f"{total:.2f}", "total": f"{total:.2f}",
            **address_fields(address_for(patient), billing_only=True),
            "clientnote": "Abijou клиникт үйлчлүүлсэнд баярлалаа!", "adminnote": MARK,
            f"custom_fields[invoice][{CF['invoice_branch']}]": branch["name"]["mn"],
            f"custom_fields[invoice][{CF['invoice_booking']}]": b["ref"]}
    for i, mode in enumerate(ALLOWED_MODES[b["country"]]):
        data[f"allowed_payment_modes[{i}]"] = mode
    for i, line in enumerate(b["lines"]):
        data.update({f"newitems[{i}][description]": line["description"],
                     f"newitems[{i}][long_description]": line.get("note", ""),
                     f"newitems[{i}][qty]": "1", f"newitems[{i}][rate]": f"{line['rate']:.2f}",
                     f"newitems[{i}][unit]": "удаа", f"newitems[{i}][order]": str(i + 1)})
    status, body = bas.call("POST", "/invoices", data=data)
    if status != 200:
        sys.exit(f"invoice {number} failed: {status} {body}")
    status, found = bas.call("GET", f"/invoices/search/{number}")
    invoice = next((r for r in (found if isinstance(found, list) else [])
                    if str(r.get("clientid")) == str(data["clientid"])), None)
    if not invoice:
        sys.exit(f"invoice {number} created but not found")
    manifest["invoices"].append(invoice["id"])
    save_manifest(manifest)
    pay = b["payment"]
    if pay["status"] != "unpaid":
        amount = total if pay["status"] == "paid" else total // 2
        # bas.mn answers 500 here even when the payment is saved; checked at the end
        bas.call("POST", "/payments", data={
            "invoiceid": invoice["id"], "amount": f"{amount:.2f}", "date": start.date().isoformat(),
            "paymentmode": MODE_ID[pay["mode"]], "transactionid": f"{pay['mode'].upper()}-{b['ref']}",
            "note": MARK})


def redo_invoices():
    """Delete the demo invoices (their payments go with them) and make them again, e.g.
    after fixing payment mode ids. Patients and appointments stay."""
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    plan = make_plan(date.fromisoformat(m["today"]))
    assign_patients(plan, m)
    bas = Bas()
    for iid in sorted(m["invoices"], key=int, reverse=True):      # bas.mn: newest first
        status, body = bas.call("DELETE", f"/invoices/{iid}")
        if status != 200:
            sys.exit(f"invoice {iid} could not be deleted: {status} {body}")
        m["invoices"].remove(iid)
        save_manifest(m)
    print("old invoices deleted", flush=True)
    patients = {p["key"]: p for p in plan["patients"]}
    number = 0
    for b in plan["bookings"]:
        if b["outcome"] == "done" and sum(l["rate"] for l in b["lines"]) > 0:
            number += 1
            make_invoice(bas, m, b, patients[b["patient"]], number)
            if number % 20 == 0:
                print(f"invoices: {number} ({bas.calls} calls)", flush=True)
    check(plan, bas)


def generate(today: date):
    """Resumable: an interrupted run continues where the manifest says it stopped
    (the plan is the same every time, from a fixed seed and the date it started)."""
    clinic = get_clinic()
    bas = Bas()
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        today = date.fromisoformat(manifest["today"])
        print(f"resuming: {len(manifest['customers'])} customers, {manifest['bookings_done']} bookings done")
    else:
        if bas.rows("/invoices"):
            sys.exit("bas.mn already has invoices; this tool numbers invoices from 1, so start from an empty tenant")
        manifest = {"created_at": datetime.now().isoformat(), "today": today.isoformat(), "customers": {},
                    "invoices": [], "events": 0, "bookings_done": 0}
        save_manifest(manifest)
    plan = make_plan(today)

    for p in plan["patients"]:
        if p["key"] in manifest["customers"]:
            continue
        branch = clinic.branch(p["branch"])
        status, body = bas.call("POST", "/customers", data={
            "company": p["name"], "phonenumber": p["phone"], **address_fields(address_for(p)),
            f"custom_fields[customers][{CF['customer_branch']}]": branch["name"]["mn"],
            f"custom_fields[customers][{CF['customer_lang']}]": p["lang"],
            f"custom_fields[customers][{CF['customer_channel']}]": p["channel"]})
        if status == 303:
            print(f"bas.mn refuses more customers at {len(manifest['customers'])} (plan limit); "
                  "the remaining bookings go to existing patients of the same branch")
            break
        if status != 200 or not body.get("record_id"):
            sys.exit(f"customer {p['name']} failed: {status} {body}")
        manifest["customers"][p["key"]] = body["record_id"]
        save_manifest(manifest)
    print(f"customers: {len(manifest['customers'])}")
    assign_patients(plan, manifest)

    number = len(manifest["invoices"])
    for b in plan["bookings"][manifest["bookings_done"]:]:
        branch = clinic.branch(b["branch"])
        patient = next(p for p in plan["patients"] if p["key"] == b["patient"])
        service = clinic.service(b["service"])
        start, end = datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])
        place = branch["name"]["mn"].split(" · ")[-1]
        title = f"{place} · {service['short']['mn']} · {patient['name']}"     # status is the colour
        note = {"done": "Ирсэн", "cancelled": "Цуцалсан", "no_show": "Ирээгүй", "upcoming": "Товлосон"}[b["outcome"]]
        if manifest.get("event_done_for") != b["ref"]:     # a resumed run may have made it already
            bas.call("POST", "/calendar", data={
                "title": title,
                "description": (f"{b['ref']} · {note}\nУтас: {patient['phone']}\nЭмчилгээ: {service['name']['mn']}\n"
                                f"Салбар: {branch['name']['mn']}\nСуваг: {patient['channel']}\n{MARK}"),
                "start": start.strftime("%Y-%m-%d %H:%M:%S"), "end": end.strftime("%Y-%m-%d %H:%M:%S"),
                "userid": 1, "color": COLORS[b["outcome"]],
                "reminder_before": 30, "reminder_before_type": "minute", "isstartnotified": 0, "public": 1})
            manifest["events"] += 1
            manifest["event_done_for"] = b["ref"]
            save_manifest(manifest)

        total = sum(l["rate"] for l in b["lines"])
        # a free consultation (Korea, ₩0) gets no invoice: bas.mn refuses a zero total
        if b["outcome"] == "done" and total > 0:
            number += 1
            make_invoice(bas, manifest, b, patient, number)
        manifest["bookings_done"] += 1
        save_manifest(manifest)
        if manifest["bookings_done"] % 20 == 0:
            print(f"bookings: {manifest['bookings_done']}/{len(plan['bookings'])} ({bas.calls} calls)", flush=True)

    check(plan, bas)


def check(plan, bas):
    invoices = bas.rows("/invoices")
    payments = bas.rows("/payments")
    print(f"bas.mn now: {len(bas.rows('/customers'))} customers, {len(invoices)} invoices, "
          f"{len(payments)} payments")
    by_status = {}
    for inv in invoices:
        by_status[inv.get("status")] = by_status.get(inv.get("status"), 0) + 1
    print("invoice statuses (1 unpaid, 2 paid, 3 partly paid, 4 overdue):", by_status)
    modes = {}
    for p in payments:
        modes[p.get("name")] = modes.get(p.get("name"), 0) + 1
    print("payments by mode:", modes)
    print(f"API calls used: {bas.calls}")


def invoice_update(inv: dict, patient: dict) -> dict:
    """bas.mn only updates an invoice sent back whole: the invoice as it is, plus the address."""
    data = {"clientid": inv["clientid"], "number": inv["number"], "date": inv["date"],
            "duedate": inv.get("duedate") or inv["date"], "currency": inv["currency"],
            "subtotal": inv["subtotal"], "total": inv["total"],
            "clientnote": inv.get("clientnote") or "", "adminnote": inv.get("adminnote") or "",
            # stored PHP-serialized; it was set from the branch's country when created
            "allowed_payment_modes": ALLOWED_MODES["kr" if patient["branch"].startswith("kr_") else "mn"],
            "items": [{"itemid": it["id"], "description": it["description"],
                       "long_description": it.get("long_description") or "", "qty": it["qty"],
                       "rate": it["rate"], "unit": it.get("unit") or "", "order": it.get("item_order") or i + 1}
                      for i, it in enumerate(inv["items"])],
            **address_fields(address_for(patient), billing_only=True)}
    return data


def addresses():
    """Give patients and invoices made before addresses existed their made-up address."""
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    plan = make_plan(date.fromisoformat(m["today"]))
    by_key = {p["key"]: p for p in plan["patients"]}
    by_id = {str(cid): by_key[key] for key, cid in m["customers"].items()}
    bas = Bas()
    done = 0
    for cid, patient in by_id.items():
        status, body = bas.call("PUT", f"/customers/{cid}", json=address_fields(address_for(patient)))
        if status != 200:
            print(f"customer {cid}: {status} {str(body)[:120]}")
        else:
            done += 1
    print(f"customers updated: {done}/{len(by_id)}")
    done = 0
    for iid in m["invoices"]:
        status, inv = bas.call("GET", f"/invoices/{iid}")
        patient = by_id.get(str(inv.get("clientid"))) if isinstance(inv, dict) else None
        if not patient:
            print(f"invoice {iid}: patient not found")
            continue
        update = invoice_update(inv, patient)
        if inv.get("billing_street") == update["billing_street"]:
            done += 1
            continue
        # bas.mn answers "Invoice Update Fail" even when it saved, so read it back instead
        bas.call("PUT", f"/invoices/{iid}", json=update)
        status, after = bas.call("GET", f"/invoices/{iid}")
        ok = (isinstance(after, dict) and after.get("billing_street") == update["billing_street"]
              and after.get("total") == inv.get("total") and after.get("status") == inv.get("status")
              and len(after.get("items", [])) == len(inv["items"]))
        if ok:
            done += 1
        else:
            print(f"invoice {iid}: not updated as expected")
    print(f"invoices updated: {done}/{len(m['invoices'])}")


def delete():
    """Remove the demo data: every invoice and appointment marked DEMO DATA (found in bas.mn,
    so a run that was cut off leaves nothing behind) and the recorded customers."""
    m = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {"customers": {}}
    bas = Bas()
    invoices = sorted(bas.rows("/invoices"), key=lambda r: int(r["id"]), reverse=True)
    deleted = 0
    for inv in invoices:                   # bas.mn only deletes the newest invoice
        if MARK not in (inv.get("adminnote") or ""):
            if deleted < len([x for x in invoices if MARK in (x.get("adminnote") or "")]):
                sys.exit(f"invoice {inv['id']} isn't demo data and is newer than demo invoices: "
                         "delete it by hand first")
            break
        status, body = bas.call("DELETE", f"/invoices/{inv['id']}")
        if status != 200:
            sys.exit(f"invoice {inv['id']}: {status} {body}")
        deleted += 1
    print(f"invoices deleted: {deleted}", flush=True)
    status, events = bas.call("GET", "/calendar")
    mine = [e for e in (events if isinstance(events, list) else []) if MARK in (e.get("description") or "")]
    for e in mine:
        bas.call("DELETE", f"/calendar/{e['eventid']}")
    print(f"appointments deleted: {len(mine)}", flush=True)
    gone = 0
    for cid in m["customers"].values():
        status, body = bas.call("DELETE", f"/customers/{cid}")
        gone += status == 200
        if status != 200:
            print(f"customer {cid}: {status} {body}")
    print(f"customers deleted: {gone}/{len(m['customers'])}")
    if MANIFEST.exists():
        MANIFEST.unlink()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m tools.basmn_demo")
    parser.add_argument("cmd", choices=["plan", "generate", "addresses", "redo-invoices", "delete"])
    parser.add_argument("--today", default=date.today().isoformat(), help="the month ends the day before this")
    args = parser.parse_args()
    today = date.fromisoformat(args.today)
    if args.cmd == "plan":
        summary(make_plan(today))
    elif args.cmd == "generate":
        generate(today)
    elif args.cmd == "addresses":
        addresses()
    elif args.cmd == "redo-invoices":
        redo_invoices()
    else:
        delete()


if __name__ == "__main__":
    main()
