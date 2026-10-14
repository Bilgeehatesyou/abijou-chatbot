"""The real-estate demo: listings for sale and rent, availability, alternatives for
listings that are gone, and booking a viewing."""
import json
import re
from datetime import timedelta

import pytest

from app import demo_data
from app.catalog import card_png, load_catalog
from app.demo import DemoEngine
from app.listings import available, price_per_m2
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


def _say(engine, store, text, sid="u1"):
    s = store.get_session(sid, "web")
    s.channel = "web"
    out = engine.handle(s, text)
    return out, [q.payload for m in out for q in (m.quick_replies or [])]


def _cards(out):
    return [c for m in out for c in (m.cards or [])]


def _open_agency(engine, store, sid="u1"):
    _say(engine, store, "", sid)
    out, buttons = _say(engine, store, "IND_real_estate", sid)
    if f"BIZ_{BIZ}" in buttons:          # only one business in the industry: opened directly
        out, buttons = _say(engine, store, f"BIZ_{BIZ}", sid)
    return out, buttons


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


# ---------- data ----------

def test_listing_data_is_consistent():
    listings = load_catalog(BIZ)
    assert len(listings.products) == 22
    statuses = {p["status"] for p in listings.products}
    assert statuses == {"available", "sold", "rented"}
    for p in listings.products:
        assert p["area_m2"] > 0 and p["offers"], p["sku"]
        assert set(p["offers"]) <= {"sale", "rent"}
        if p["status"] == "sold":
            assert "sale" in p["offers"]
        if p["status"] == "rented":
            assert "rent" in p["offers"]
        if price_per_m2(p):
            assert f"{price_per_m2(p):,}₮" in listings.details(p, "mn")
        for lang in ("mn", "en"):
            assert len(f"🏠 {p['short'][lang]}") <= 20         # Messenger quick-reply limit
            assert len(listings.card(p, lang, "").subtitle) <= 80
        assert p["area_id"] in listings.areas


def test_floor_is_written_building_then_unit():
    p = load_catalog(BIZ).by_sku["RE07"]
    assert "9/3 давхарт" in load_catalog(BIZ).details(p, "mn")
    assert "floor 3 of 9" in load_catalog(BIZ).details(p, "en")


def test_details_list_every_offer_and_its_terms():
    listings = load_catalog(BIZ)
    text = listings.details(listings.by_sku["RE07"], "mn")
    assert "Худалдах: 205,000,000₮ (1 м² 5,662,983₮) · Нөхцөл: Бэлэн болон банкны зээлээр" in text
    assert "Түрээс: 1,300,000₮/сар · Нөхцөл: 3+1 сар" in text
    assert "✅ Боломжтой" in text
    office = listings.details(listings.by_sku["RE15"], "en")
    assert "🔴 Rented out" in office and "per m² 88,000₮/month" in office


@pytest.mark.parametrize("query, expected", [
    ("Зайсанд 3 өрөө", ["RE08"]),
    ("yarmagt 2 uruu", ["RE03"]),
    ("house in Nukht", ["RE21"]),
    ("Ногоон Тал хотхонд 3 өрөө байр байна уу", ["RE02", "RE01"]),   # same building, one sold
    ("Тэнгэр Резиденс", ["RE08", "RE09"]),
    ("Гачуурт байшин", ["RE22"]),                                    # sold, named by area + kind
    ("хотын төвд оффис", ["RE15"]),                                  # rented, named by area + kind
    ("оффис түрээс", ["RE16"]),
    ("зогсоол", ["RE19"]),
    ("RE05", ["RE05"]),
    ("хоол", []),
    ("та нар хаана байрладаг вэ", []),
])
def test_search(query, expected):
    assert [p["sku"] for p in load_catalog(BIZ).search(query)] == expected


def test_general_search_hides_what_is_gone():
    listings = load_catalog(BIZ)
    for query in ("байр", "Зайсан", "түрээсийн байр", "400 сая хүртэл байр"):
        assert all(available(p) for p in listings.search(query)), query


def test_rent_and_budget_search():
    listings = load_catalog(BIZ)
    rent = listings.search("2 сая хүртэл түрээс")
    assert rent and all("rent" in p["offers"] and p["offers"]["rent"]["monthly_mnt"] <= 2_100_000 for p in rent)
    buy = listings.search("400 сая хүртэл байр")
    assert buy and all(p["type"] == "apartment" and p["offers"]["sale"]["price_mnt"] <= 420_000_000 for p in buy)


def test_alternatives_same_building_first_then_nearby():
    listings = load_catalog(BIZ)
    alts = lambda sku: [(q["sku"], why) for q, why, _ in listings.alternatives(listings.by_sku[sku])]
    assert alts("RE01") == [("RE02", "same_building"), ("RE04", "nearby")]    # sold flat
    assert alts("RE05") == [("RE06", "same_building"), ("RE03", "nearby")]    # rented flat
    assert alts("RE09") == [("RE08", "same_building")]
    assert alts("RE22") == [] and alts("RE15") == []                          # nothing similar


def test_card_images_render():
    for sku in ("RE01", "RE07", "RE15", "RE19"):
        assert card_png(BIZ, sku, "mn").startswith(b"\x89PNG")
    assert card_png("wholesale", "MCC001", "mn").startswith(b"\x89PNG")   # products still work


def test_sync_loads_new_and_changed_files_only(store):
    assert BIZ in demo_data.sync_businesses(store)
    assert demo_data.sync_businesses(store) == []
    store.crm_state_set(f"demo_data:{BIZ}", "stale")           # the file changed since
    assert demo_data.sync_businesses(store) == [BIZ]
    assert store.get_business(BIZ)["name_mn"] == "Өргөө Хаус үл хөдлөх хөрөнгө"
    assert len(store.get_faqs(BIZ)) == 26


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
    cards = _cards(out)
    assert [c.buttons[-1].payload for c in cards] == ["VIEW_RE08"]
    assert "7.69 сая₮/м²" in cards[0].subtitle


def test_sold_flat_offers_the_same_building_without_repeating_cards(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, _ = _say(engine, store, "Ногоон Тал хотхонд 3 өрөө байр байна уу")
    first, follow = out[0], out[1]
    assert [c.buttons[0].payload for c in first.cards] == ["INFO_RE02", "INFO_RE01"]
    assert first.cards[1].buttons[1].payload == "SIMILAR_RE01"       # no viewing of a sold flat
    assert "зарагдсан" in follow.text and "яг тэр байранд, 12/6 давхарт" in follow.text
    assert "0.7 км зайтай" in follow.text
    assert [c.buttons[0].payload for c in follow.cards] == ["INFO_RE04"]  # RE02 is already shown


def test_viewing_a_rented_flat_is_refused_with_alternatives(setup, store):
    engine, cal = setup
    _open_agency(engine, store)
    out, buttons = _say(engine, store, "VIEW_RE05")
    assert "түрээслэгдсэн тул үзэх цаг авах боломжгүй" in out[0].text
    assert [c.buttons[1].payload for c in _cards(out)] == ["VIEW_RE06", "VIEW_RE03"]
    assert not any(b.startswith("BDAY_") for b in buttons) and cal.events == []


def test_nothing_similar_asks_area_then_type(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, buttons = _say(engine, store, "Гачуурт байшин")
    assert "ойролцоо төстэй зар одоогоор алга" in out[-1].text
    assert "PREFA_nukht" in buttons and "PREFA_gachuurt" not in buttons    # nothing left there
    out, buttons = _say(engine, store, "PREFA_nukht")
    assert out[-1].text.startswith("Нүхт орчимд") and "PREF_nukht_house" in buttons
    out, _ = _say(engine, store, "PREF_nukht_house")
    assert "Нүхт, 5 өрөө хаус — яг энэ хавьд" in out[-1].text
    assert [c.buttons[1].payload for c in _cards(out)] == ["VIEW_RE21"]


def test_recommendations_are_closest_first(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, _ = _say(engine, store, "PREF_yarmag_apartment")
    skus = [c.buttons[0].payload[5:] for c in _cards(out)]
    listings = load_catalog(BIZ)
    distances = [listings.distance_from("yarmag", listings.by_sku[s]) for s in skus]
    assert skus and distances == sorted(distances) and all(available(listings.by_sku[s]) for s in skus)


def test_details_of_a_sold_listing_come_with_alternatives(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, _ = _say(engine, store, "INFO_RE09")
    assert "🔴 Зарагдсан" in out[0].text
    assert [c.buttons[0].payload for c in _cards(out)] == ["INFO_RE08"]


def test_browse_shows_only_available(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, buttons = _say(engine, store, "CAT")
    assert {"CAT_apartment", "CAT_house", "CAT_office", "CAT_parking", "CAT_land"} <= set(buttons)
    out, _ = _say(engine, store, "CAT_house")
    assert [c.buttons[0].payload for c in _cards(out)] == ["INFO_RE21"]     # RE22 is sold


def test_viewing_from_a_card_books_that_property(setup, store):
    engine, cal = setup
    _open_agency(engine, store)
    _, buttons = _say(engine, store, "VIEW_RE11")
    assert any(b.startswith("BDAY_") for b in buttons)            # straight to the day: no service step
    summary, done = _book_through(engine, store, buttons)

    assert "Хотын төв, студио, Хотын Зүрх" in summary and "Хотын Зүрх цогцолбор" in summary
    assert "✅" in done and "Хотын Зүрх цогцолбор" in done
    # the business got its own calendar, shared with everyone listed
    assert cal.calendars == ["Өргөө Хаус үл хөдлөх хөрөнгө · Ajilt-AI демо"]
    assert [e for _, e in cal.shared] == ["a@example.com", "b@example.com"]
    (event,) = cal.events
    assert event["summary"].startswith("Байр үзэх: Төв студио — Бат-Эрдэнэ")
    assert event["location"].startswith("Сүхбаатар дүүрэг, Хотын төв, Хотын Зүрх")
    assert "RE11" in event["description"] and event["private"]["item"] == "RE11"
    assert event["end"] - event["start"] == timedelta(minutes=45)
    with store._conn() as c:
        row = c.execute("SELECT * FROM bookings").fetchone()
    assert row["business_id"] == BIZ and row["service_id"] == "viewing" and row["event_id"] == "ev1"


def test_book_button_asks_which_property(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, buttons = _say(engine, store, "BOOK")
    assert out[-1].text.startswith("Аль байрыг")
    assert "VIEW_RE02" in buttons and "BOOK_CONSULT" in buttons and len(buttons) <= 13
    assert "VIEW_RE01" not in buttons                               # sold: never offered

    _say(engine, store, "Яармагт 2 өрөө")                          # one card shown...
    out, buttons = _say(engine, store, "BOOK")                     # ...so that one is booked
    assert any(b.startswith("BDAY_") for b in buttons)


def test_consultation_happens_at_the_office(setup, store):
    engine, cal = setup
    _open_agency(engine, store)
    _, buttons = _say(engine, store, "BOOK_CONSULT")
    summary, done = _book_through(engine, store, buttons)
    assert "Зөвлөгөө" in summary and "Их тойруу 21" in done
    assert cal.events[0]["location"].startswith("Сүхбаатар дүүрэг, 8-р хороо, Их тойруу 21")


def test_llm_gets_status_offers_and_alternatives(store, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "BASMN_API_KEY", "")
    llm = ScriptedLLM("Тийм, RE08-ийг үзэх цаг товлоё. [BOOK]")
    engine = DemoEngine(llm=llm, store=store, calendar=FakeCalendar())
    _open_agency(engine, store)
    out, buttons = _say(engine, store, "Зайсанд 3 өрөө байр очиж үзмээр байна")
    system = llm.prompts[-1][0]["content"]
    assert system.count("\nRE") == 22
    assert "RE01 | SOLD" in system and "ALTERNATIVES: RE02 (same building, floor 6 of 12), RE04 (0.7 km away)" in system
    assert "RE22 | SOLD" in system and "ALTERNATIVES: none — ask which area and type they want" in system
    assert "FOR RENT 1,300,000 MNT a month" in system and "FOR SALE 205,000,000 MNT (5,662,983 MNT per m²)" in system
    assert "shown as picture cards under your reply: RE08" in system
    assert out[0].text == "Тийм, RE08-ийг үзэх цаг товлоё."
    assert any(b.startswith("BDAY_") for b in buttons)            # booking RE08 straight away


def test_wholesale_catalog_is_unchanged():
    catalog = load_catalog("wholesale")
    p = catalog.by_sku["MCC001"]
    assert catalog.card(p, "mn", "").buttons[0].payload == "ORDER_MCC001"
    assert "PRODUCT CATALOG: 380 products" in catalog.prompt_context([p], "en")
    assert re.search(r"≈ [\d,]+₮", catalog.card(p, "mn", "").subtitle)


def test_llm_offering_a_viewing_does_not_start_booking(store, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "BASMN_API_KEY", "")
    llm = ScriptedLLM("RE02 боломжтой, RE01 зарагдсан. RE02-ийг үзэх цаг товлох уу? [BOOK]")
    engine = DemoEngine(llm=llm, store=store, calendar=FakeCalendar())
    _open_agency(engine, store)
    out, buttons = _say(engine, store, "Ногоон Тал хотхонд 3 өрөө байр байна уу?")
    assert out[0].text.endswith("товлох уу?") and "[BOOK]" not in out[0].text
    assert not any(b.startswith("BDAY_") for b in buttons)            # no booking without a yes
    assert "яг тэр байранд" in out[1].text                              # the sold one's alternatives


def test_a_question_during_booking_leaves_it(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    _, buttons = _say(engine, store, "VIEW_RE02")
    assert any(b.startswith("BDAY_") for b in buttons)
    out, buttons = _say(engine, store, "Түрээсийн байр байгаа юу?")
    assert not out[0].text.startswith("Доорх товчнуудаас")
    assert _cards(out) and all("rent" in load_catalog(BIZ).by_sku[c.buttons[0].payload[5:]]["offers"]
                               for c in _cards(out))
    s = store.get_session("u1", "web")
    assert s.state == "CHAT" and "book" not in s.data


def test_a_card_button_during_booking_leaves_it(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    _say(engine, store, "VIEW_RE02")
    out, _ = _say(engine, store, "INFO_RE04")
    assert "RE04" in out[0].text and store.get_session("u1", "web").state == "CHAT"


def test_numbered_answer_still_continues_the_booking(setup, store):
    """ZevChat and others answer with the option's number; that is not a new question."""
    engine, _ = setup
    _open_agency(engine, store)
    _say(engine, store, "VIEW_RE02")
    out, buttons = _say(engine, store, "1")
    assert any(b.startswith("BTIME_") for b in buttons)


def test_this_one_means_the_listing_last_opened(store, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "BASMN_API_KEY", "")
    llm = ScriptedLLM("Тийм, банкны ипотекоор авч болно.")
    engine = DemoEngine(llm=llm, store=store, calendar=FakeCalendar())
    _open_agency(engine, store)
    _say(engine, store, "Гачуурт байшин")                  # earlier talk about another listing
    _say(engine, store, "VIEW_RE08")                        # then the Zaisan card's booking button
    out, _ = _say(engine, store, "Энэ байр ипотекоор авч болох уу?")
    system = llm.prompts[-1][0]["content"]
    assert "now looking at RE08" in system
    assert [c.buttons[0].payload for c in _cards(out)] == ["INFO_RE08"]
    assert store.get_session("u1", "web").state == "CHAT"   # the question left the booking


def test_a_general_question_shows_no_cards(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, _ = _say(engine, store, "Байр үзэхэд төлбөртэй юу?")
    assert _cards(out) == []
    assert out[0].text.startswith("Үгүй, байр үзэх")                     # the FAQ answer
