"""The real-estate demo: listings search, cards, details and booking a viewing."""
import json
import re

import pytest

from app import demo_data
from app.catalog import card_png, load_catalog
from app.demo import DemoEngine
from app.llm import NullLLM
from app.store import Store

BIZ = "real_estate"


class FakeCalendar:
    """Google Calendar stand-in: records what the booking flow writes."""
    email = "bot@example.iam.gserviceaccount.com"

    def __init__(self):
        self.calendars, self.shared, self.events = [], [], []

    def create_calendar(self, title):
        self.calendars.append(title)
        return f"cal{len(self.calendars)}"

    def share(self, calendar_id, email, role="owner"):
        self.shared.append((calendar_id, email))

    def busy(self, calendar_id, start, end, branch=None):
        return []

    def create_event(self, calendar_id, summary, description, start, end, location="",
                     private=None, color_id=""):
        self.events.append(dict(calendar_id=calendar_id, summary=summary, description=description,
                                start=start, end=end, location=location, private=private))
        return {"id": f"ev{len(self.events)}"}


class ScriptedLLM(NullLLM):
    """Answers with a fixed reply and keeps the prompt it was given."""

    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def chat(self, messages, temperature=0.3, timeout=None, **kw):
        self.prompts.append(messages)
        return self.reply


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "t.db"))


@pytest.fixture
def setup(store, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "BASMN_API_KEY", "")
    monkeypatch.setattr(settings, "BOOKING_CALENDAR_SHARE_WITH", "a@example.com, b@example.com")
    cal = FakeCalendar()
    return DemoEngine(llm=NullLLM(), store=store, calendar=cal), cal


def _session(store, sid="u1"):
    s = store.get_session(sid, "web")
    s.channel = "web"
    return s


def _say(engine, store, text, sid="u1"):
    s = _session(store, sid)
    out = engine.handle(s, text)
    return out, [q.payload for m in out for q in (m.quick_replies or [])]


def _open_agency(engine, store, sid="u1"):
    _say(engine, store, "", sid)
    out, buttons = _say(engine, store, "IND_real_estate", sid)
    if f"BIZ_{BIZ}" in buttons:          # only one business in the industry: opened directly
        out, buttons = _say(engine, store, f"BIZ_{BIZ}", sid)
    return out, buttons


# ---------- data ----------

def test_listing_numbers_are_consistent():
    listings = load_catalog(BIZ)
    assert len(listings.products) == 16
    for p in listings.products:
        assert p["price_mnt"] > 0 and p["area_m2"] > 0
        assert listings.details(p, "mn").count(f"{round(p['price_mnt'] / p['area_m2']):,}₮") == 1
        for lang in ("mn", "en"):
            assert len(f"🏠 {p['short'][lang]}") <= 20         # Messenger quick-reply limit
            assert len(listings.card(p, lang, "").subtitle) <= 80


@pytest.mark.parametrize("query, expected", [
    ("Зайсанд 3 өрөө байр байгаа юу", ["RE01"]),
    ("zaisand 3 uruu", ["RE01"]),
    ("yarmagt 2 uruu bair", ["RE02"]),
    ("house in Nukht", ["RE11"]),
    ("1 тэрбумаас дээш хаус", ["RE12", "RE11"]),
    ("RE07 хэд вэ", ["RE07"]),
    ("хоол", []),
    ("та нар хаана байрладаг вэ", []),
])
def test_search(query, expected):
    assert [p["sku"] for p in load_catalog(BIZ).search(query)] == expected


def test_budget_search_respects_the_budget():
    found = load_catalog(BIZ).search("400 сая хүртэл байр")
    assert found and all(p["price_mnt"] <= 420_000_000 and p["type"] == "apartment" for p in found)
    assert [p["price_mnt"] for p in found] == sorted(p["price_mnt"] for p in found)


def test_card_images_render():
    png = card_png(BIZ, "RE01", "mn")
    assert png.startswith(b"\x89PNG")
    assert card_png("wholesale", "MCC001", "mn").startswith(b"\x89PNG")   # products still work


def test_sync_loads_new_and_changed_files_only(store, monkeypatch):
    assert BIZ in demo_data.sync_businesses(store)
    assert demo_data.sync_businesses(store) == []
    store.crm_state_set(f"demo_data:{BIZ}", "stale")           # the file changed since
    assert demo_data.sync_businesses(store) == [BIZ]
    biz = store.get_business(BIZ)
    assert biz["name_mn"] == "Өргөө Хаус үл хөдлөх хөрөнгө" and len(store.get_faqs(BIZ)) == 22


def test_existing_data_is_adopted_not_reloaded(store):
    seeded = json.loads(open("data/demo/businesses/dental.json", encoding="utf-8").read())
    seeded["faqs"] = seeded["faqs"][:1]                         # what a hand load put there
    store.replace_business(seeded)
    assert "dental" not in demo_data.sync_businesses(store)
    assert len(store.get_faqs("dental")) == 1


# ---------- conversation ----------

def test_agency_intro_offers_listings_and_booking(setup, store):
    engine, _ = setup
    out, buttons = _open_agency(engine, store)
    assert "Өргөө Хаус" in out[-1].text
    assert {"CAT", "BOOK", "TOUR_START"} <= set(buttons)


def test_question_shows_matching_cards(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, _ = _say(engine, store, "Зайсанд 3 өрөө байр байгаа юу")
    cards = [c for m in out for c in (m.cards or [])]
    assert [c.buttons[-1].payload for c in cards] == ["VIEW_RE01"]
    assert "7.69 сая₮/м²" in cards[0].subtitle


def test_browse_and_details(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, buttons = _say(engine, store, "CAT")
    assert {"CAT_apartment", "CAT_house", "CAT_office", "CAT_land"} <= set(buttons)
    out, _ = _say(engine, store, "CAT_house")
    assert [c.title for c in out[-1].cards][0].startswith("Гачуурт")      # cheapest first
    out, buttons = _say(engine, store, "INFO_RE11")
    assert "1,950,000,000₮" in out[-1].text and "7,500,000₮" in out[-1].text
    assert buttons[0] == "VIEW_RE11"


def _book_through(engine, store, buttons, sid="u1"):
    """Day -> time -> name -> phone -> confirm, from wherever the flow starts."""
    if any(b.startswith("BDAY_") for b in buttons):
        _, buttons = _say(engine, store, next(b for b in buttons if b.startswith("BDAY_")), sid)
    _, buttons = _say(engine, store, next(b for b in buttons if b.startswith("BTIME_")), sid)
    _say(engine, store, "Бат-Эрдэнэ", sid)
    out, _ = _say(engine, store, "99112233", sid)
    summary = out[-1].text
    out, _ = _say(engine, store, "BOK", sid)
    return summary, out[0].text


def test_viewing_from_a_card_books_that_property(setup, store):
    engine, cal = setup
    _open_agency(engine, store)
    _, buttons = _say(engine, store, "VIEW_RE03")
    assert any(b.startswith("BDAY_") for b in buttons)            # straight to the day: no service step
    summary, done = _book_through(engine, store, buttons)

    assert "Хотын төв, 3 өрөө, Төв Өргөө" in summary and "Төв Өргөө цогцолбор" in summary
    assert "✅" in done and "Төв Өргөө цогцолбор, 2-р байр" in done
    # the business got its own calendar, shared with everyone listed
    assert cal.calendars == ["Өргөө Хаус үл хөдлөх хөрөнгө · Ajilt-AI демо"]
    assert [e for _, e in cal.shared] == ["a@example.com", "b@example.com"]
    (event,) = cal.events
    assert event["summary"].startswith("Байр үзэх: Төв 3 өрөө — Бат-Эрдэнэ")
    assert event["location"].startswith("Сүхбаатар дүүрэг, 1-р хороо, Төв Өргөө")
    assert "RE03" in event["description"] and event["private"]["item"] == "RE03"
    assert event["end"] - event["start"] == __import__("datetime").timedelta(minutes=45)
    with store._conn() as c:
        row = c.execute("SELECT * FROM bookings").fetchone()
    assert row["business_id"] == BIZ and row["service_id"] == "viewing" and row["event_id"] == "ev1"


def test_book_button_asks_which_property(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, buttons = _say(engine, store, "BOOK")
    assert out[-1].text.startswith("Аль байрыг")
    assert "VIEW_RE01" in buttons and "BOOK_CONSULT" in buttons and len(buttons) <= 13

    _say(engine, store, "Яармагт 2 өрөө")                        # one card shown...
    out, buttons = _say(engine, store, "BOOK")                   # ...so that one is booked
    assert any(b.startswith("BDAY_") for b in buttons)


def test_consultation_happens_at_the_office(setup, store):
    engine, cal = setup
    _open_agency(engine, store)
    _, buttons = _say(engine, store, "BOOK_CONSULT")
    summary, done = _book_through(engine, store, buttons)
    assert "Зөвлөгөө" in summary and "Их тойруу 21" in done
    assert cal.events[0]["location"].startswith("Сүхбаатар дүүрэг, 8-р хороо, Их тойруу 21")


def test_llm_gets_every_listing_and_can_start_a_viewing(store, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "BASMN_API_KEY", "")
    llm = ScriptedLLM("Тийм, RE01-ийг үзэх цаг товлоё. [BOOK]")
    engine = DemoEngine(llm=llm, store=store, calendar=FakeCalendar())
    _open_agency(engine, store)
    out, buttons = _say(engine, store, "Зайсанд 3 өрөө байр очиж үзмээр байна")
    system = llm.prompts[-1][0]["content"]
    assert system.count("MNT per m²") == 16 and "7,688,889 MNT per m²" in system
    assert "shown as picture cards under your reply: RE01" in system
    assert out[0].text == "Тийм, RE01-ийг үзэх цаг товлоё."
    assert any(b.startswith("BDAY_") for b in buttons)            # booking RE01 straight away


def test_wholesale_catalog_is_unchanged(setup, store):
    catalog = load_catalog("wholesale")
    p = catalog.by_sku["MCC001"]
    assert catalog.card(p, "mn", "").buttons[0].payload == "ORDER_MCC001"
    assert "PRODUCT CATALOG: 380 products" in catalog.prompt_context([p], "en")
    assert re.search(r"≈ [\d,]+₮", catalog.card(p, "mn", "").subtitle)
