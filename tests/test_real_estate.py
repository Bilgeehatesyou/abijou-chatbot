"""The real-estate demo (Gerlug Vista and Hunnu 2222): listings for sale and rent,
availability, alternatives for listings that are gone, units that don't exist, the
rooms/complex/payment questions, and booking a viewing."""
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
    assert len(listings.products) == 273
    assert {p["status"] for p in listings.products} == {"available", "sold", "rented", "reserved"}
    assert set(listings.complexes) == {"gv", "hn"}
    for p in listings.products:
        assert p["area_m2"] > 0 and p["offers"], p["sku"]
        assert set(p["offers"]) <= {"sale", "rent"}
        if p["status"] == "sold":
            assert "sale" in p["offers"]
        if p["status"] == "rented":
            assert "rent" in p["offers"]
        if price_per_m2(p):
            assert f"{price_per_m2(p):,}₮" in listings.details(p, "mn")
            if listings._complex(p):                              # Khan-Uul 2024-2026 asking prices
                assert 6.5e6 < price_per_m2(p) < 10.5e6, p["sku"]
            else:
                assert 2e6 < price_per_m2(p) < 10e6, p["sku"]
        for lang in ("mn", "en"):
            assert len(f"🏠 {p['short'][lang]}") <= 20         # Messenger quick-reply limit
            assert len(listings.card(p, lang, "").subtitle) <= 80
        assert p["area_id"] in listings.areas and p["floor"] <= p["floors"]
    # both complexes have every kind of flat, available and sold, and parking
    for cx in ("gv", "hn"):
        mine = [p for p in listings.products if listings._complex(p) == cx]
        for rooms in (2, 3, 4, 5):
            kinds = {p["status"] for p in mine if p["type"] == "apartment" and p["rooms"] == rooms}
            assert {"available", "sold"} <= kinds, (cx, rooms)
        assert {"available", "sold"} <= {p["status"] for p in mine if p["type"] == "parking"}
    units = [(p["area_id"], p["block"], p["floor"], p["area_m2"]) for p in listings.products
             if p["type"] == "apartment"]
    assert len(units) == len(set(units))                         # no flat listed twice
    # the rest of the city: every neighbourhood and numbered microdistrict has flats, free and sold
    others = [a for a in listings.areas if a not in ("gerlug", "hunnu")]
    assert len(others) == 23 and {"zaisan", "yarmag", "nisekh", "mcr13", "mcr10"} <= set(others)
    assert sorted(a["micro"] for a in listings.areas.values() if a.get("micro")) == [1, 3, 4, 10, 11, 12, 13, 14, 15, 16]
    for a in others:
        assert {"available", "sold"} <= {p["status"] for p in listings.products if p["area_id"] == a}, a


def test_floor_is_written_storeys_then_unit():
    listings = load_catalog(BIZ)
    p = listings.by_sku["GV02"]
    assert "16/5 давхарт" in listings.details(p, "mn")
    assert "floor 5 of 16" in listings.details(p, "en")


def test_details_list_every_offer_terms_and_payment():
    listings = load_catalog(BIZ)
    text = listings.details(listings.by_sku["GV30"], "mn")
    assert "Худалдах: 535,000,000₮ (1 м² 8,438,486₮) · Нөхцөл: Бэлэн, банкны зээл, 8%-ийн ипотек" in text
    assert "Түрээс: 2,800,000₮/сар · Нөхцөл: 3+1 сар" in text
    assert "✅ Боломжтой" in text and "🛠 Шинэ засвартай" in text
    new = listings.details(listings.by_sku["GV36"], "en")      # block 42: no certificate yet
    assert "Terms: Cash" in new and "Certificate not issued yet" in new
    assert "🔄 Бартер: машин" in listings.details(listings.by_sku["GV41"], "mn")


@pytest.mark.parametrize("query, expected", [
    ("Гэрлүг Виста 40-р байр 9 давхар 3 өрөө", ["GV01"]),           # sold, named exactly
    ("gerlug vista 40r bair 5 dawhar 3 uruu", ["GV02"]),
    ("Хүннү 2222 10-р байр 21 давхар", ["HN01"]),
    ("GV07", ["GV07"]),
    ("хоол", []),
    ("та нар хаана байрладаг вэ", []),
    ("Байр бартераар авч болох уу?", []),                             # a question, not a search
])
def test_search(query, expected):
    assert [p["sku"] for p in load_catalog(BIZ).search(query)] == expected


@pytest.mark.parametrize("query, check", [
    ("Гэрлүг вистад 4 өрөө", lambda p: p["building"]["complex"]["id"] == "gv" and p["rooms"] == 4),
    ("Хүннү 2222 2-р ээлжинд 3 өрөө", lambda p: p.get("phase") == 2 and p["rooms"] == 3),
    ("hunnu 2222 plas", lambda p: p.get("phase") == "plus"),
    ("hunnu 2222 garaj", lambda p: p["building"]["complex"]["id"] == "hn" and p["type"] == "parking"),
    ("Зайсанд 3 өрөө", lambda p: p["area_id"] == "zaisan" and p["rooms"] == 3),
    ("13-р хороололд 2 өрөө байр", lambda p: p["area_id"] == "mcr13" and p["rooms"] == 2),
    ("13r horoolold 2 uruu", lambda p: p["area_id"] == "mcr13" and p["rooms"] == 2),
    ("11-р хороолол", lambda p: p["area_id"] == "mcr11"),
    ("10 hor 3 uruu", lambda p: p["area_id"] == "mcr10" and p["rooms"] == 3),
    ("yarmagt 2 uruu bair hed ve", lambda p: p["area_id"] == "yarmag" and p["rooms"] == 2),
    ("Нисэхэд байр", lambda p: p["area_id"] == "nisekh"),
    ("Хүннүд 2 өрөө түрээс", lambda p: p["area_id"] == "hunnu" and p["rooms"] == 2 and "rent" in p["offers"]),
    ("бартераар 3 өрөө", lambda p: p["rooms"] == 3 and "barter" in p["pay"]),
    ("зээлээр 2 өрөө Гэрлүг", lambda p: p["area_id"] == "gerlug" and "loan" in p["pay"]),
])
def test_search_by_complex_rooms_phase_and_payment(query, check):
    found = load_catalog(BIZ).search(query)
    assert found and all(available(p) and check(p) for p in found), query


def test_general_search_hides_what_is_gone():
    listings = load_catalog(BIZ)
    for query in ("байр", "Гэрлүг Виста", "Хүннү 2222 түрээс", "700 сая хүртэл байр", "зогсоол"):
        found = listings.search(query)
        assert found and all(available(p) for p in found), query
    assert listings.search("Хүннү 2222")[0]["type"] == "apartment"    # flats before parking


def test_rent_and_budget_search():
    listings = load_catalog(BIZ)
    rent = listings.search("3 сая хүртэл түрээс")
    assert rent and all("rent" in p["offers"] and p["offers"]["rent"]["monthly_mnt"] <= 3_150_000 for p in rent)
    buy = listings.search("700 сая хүртэл байр")
    assert buy and all(p["type"] == "apartment" and p["offers"]["sale"]["price_mnt"] <= 735_000_000 for p in buy)


def test_a_unit_that_does_not_exist_is_reported_with_the_closest():
    listings = load_catalog(BIZ)
    found, missing = listings.find("gerlug vista 40r bair 20 dawhar 3 uruu")    # block 40 has 16 storeys
    assert missing["mn"] == "Гэрлүг Виста хотхон, 40-р байр, 20 давхарт 3 өрөө байр"
    assert missing["en"] == "a 3-room flat on floor 20 in Gerlug Vista complex, bldg 40"
    assert found[0]["sku"] == "GV02"                               # same block first
    assert all(available(p) and p["rooms"] == 3 and p["area_id"] == "gerlug" for p in found)
    found, missing = listings.find("Хүннү 2222 6 өрөө")            # Hunnu has no 6-room flats
    assert missing["mn"] == "Хүннү 2222 хотхон, 6 өрөө байр"
    assert found and all(p["area_id"] == "hunnu" and p["rooms"] == 5 for p in found[:4])
    assert listings.find("HN99") == ([], {"mn": "HN99 кодтой зар", "en": "listing HN99"})
    assert listings.find("Гэрлүг Виста 3 өрөө")[1] is None
    found, missing = listings.find("7-р хороолол 2 өрөө")          # no such microdistrict here
    assert missing["mn"] == "7-р хороолол, 2 өрөө байр" and found and all(p["rooms"] == 2 for p in found)
    found, missing = listings.find("Зайсан 78-р байр 20 давхар 3 өрөө")
    assert missing["mn"] == "Зайсан, 78-р байр, 20 давхарт 3 өрөө байр"
    assert found[0]["area_id"] == "zaisan" and found[0]["rooms"] == 3
    assert listings.find("хоол") == ([], None)


def test_alternatives_same_building_then_complex_then_nearby():
    listings = load_catalog(BIZ)
    alts = lambda sku: [(q["sku"], why) for q, why, _ in listings.alternatives(listings.by_sku[sku])]
    assert alts("GV01")[0] == ("GV02", "same_building")             # 3-room sold: floor 5 of block 40
    assert alts("GV04")[0] == ("GV12", "same_complex")              # no 4-room left in block 38
    assert {why for _, why in alts("GV04")} == {"same_complex"}
    assert {why for _, why in alts("GV08")} == {"nearby"}          # no 3-room rental left in Gerlug
    assert alts("UB01")[0] == ("UB02", "same_building")            # neighbourhood flats too
    assert alts("HN01")[0] == ("HN02", "same_building")
    assert alts("HN03")[0] == ("HN04", "same_building")             # rented: the floor above
    assert alts("GV07") == []                                       # the penthouse: nothing like it


def test_card_images_render():
    for sku in ("GV01", "GV30", "HN49", "GV07"):
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
    assert {"CAT", "BOOK", "TOUR_START", "WANT_START"} <= set(buttons)


def test_question_shows_matching_cards(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, _ = _say(engine, store, "Гэрлүг Виста 40-р байр 5 давхар 3 өрөө байгаа юу")
    cards = _cards(out)
    assert [c.buttons[-1].payload for c in cards] == ["VIEW_GV02"]
    assert "8.58 сая₮/м²" in cards[0].subtitle


def test_sold_flat_offers_another_floor_of_the_same_building(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, _ = _say(engine, store, "gerlug vista 40r bair 9 dawhar 3 uruu")
    first, follow = out[0], out[1]
    assert [c.buttons[1].payload for c in first.cards] == ["SIMILAR_GV01"]   # no viewing of a sold flat
    lines = follow.text.splitlines()
    assert "зарагдсан" in lines[0] and "яг тэр байранд, 16/5 давхарт" in lines[1]
    assert "мөн хотхоны 39-р байр" in follow.text
    assert follow.cards[0].buttons[1].payload == "VIEW_GV02"


def test_sold_flat_offers_another_block_of_the_same_complex(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, _ = _say(engine, store, "Гэрлүг Виста хотхоны 38-р байрны 11 давхрын 4 өрөө байр")
    assert [c.buttons[1].payload for c in out[0].cards] == ["SIMILAR_GV04"]
    assert "зарагдсан" in out[1].text and "мөн хотхоны 37-р байр, 12/11 давхарт" in out[1].text
    assert out[1].cards[0].buttons[1].payload == "VIEW_GV12"


def test_rented_flat_with_nothing_in_its_complex_offers_the_other_complex(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, _ = _say(engine, store, "Гэрлүг Виста 37-р байр 6 давхар түрээс")
    assert "түрээслэгдсэн" in out[1].text and "км зайтай" in out[1].text
    listings = load_catalog(BIZ)
    alts = [listings.by_sku[c.buttons[1].payload[5:]] for c in out[1].cards]
    assert alts and all("rent" in p["offers"] and p["area_id"] != "gerlug" for p in alts)


def test_viewing_a_rented_flat_is_refused_with_alternatives(setup, store):
    engine, cal = setup
    _open_agency(engine, store)
    out, buttons = _say(engine, store, "VIEW_HN03")
    assert "түрээслэгдсэн тул үзэх цаг авах боломжгүй" in out[0].text
    assert _cards(out)[0].buttons[1].payload == "VIEW_HN04"
    assert not any(b.startswith("BDAY_") for b in buttons) and cal.events == []


def test_sold_flat_with_nothing_similar_asks_where_and_what(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, buttons = _say(engine, store, "Гэрлүг Виста 6 өрөө")
    assert "Та хаана, ямар байр авахыг хүсэж байна вэ?" in out[-1].text
    assert {"PREFA_gerlug", "PREFA_hunnu"} <= set(buttons)
    out, buttons = _say(engine, store, "PREFA_hunnu")
    assert out[-1].text.startswith("Хүннү 2222 орчимд") and "PREF_hunnu_parking" in buttons
    out, _ = _say(engine, store, "PREF_hunnu_parking")
    parking = [load_catalog(BIZ).by_sku[c.buttons[0].payload[5:]] for c in _cards(out)]
    assert parking and all(p["type"] == "parking" for p in parking)
    assert [p["area_id"] for p in parking] == sorted((p["area_id"] for p in parking), key=lambda a: a != "hunnu")


def test_recommendations_are_closest_first(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, _ = _say(engine, store, "PREF_gerlug_apartment")
    skus = [c.buttons[0].payload[5:] for c in _cards(out)]
    listings = load_catalog(BIZ)
    distances = [listings.distance_from("gerlug", listings.by_sku[s]) for s in skus]
    assert skus and distances == sorted(distances) and all(available(listings.by_sku[s]) for s in skus)


def test_details_of_a_sold_listing_come_with_alternatives(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, _ = _say(engine, store, "INFO_HN01")
    assert "🔴 Зарагдсан" in out[0].text
    assert _cards(out)[0].buttons[0].payload == "INFO_HN02"


def test_details_then_ask_to_view_or_what_would_suit(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, buttons = _say(engine, store, "INFO_GV02")
    assert "GV02" in out[0].text and "бартер" in out[1].text and "хэдэн өрөө" in out[1].text
    assert buttons[0] == "VIEW_GV02" and "WANT_START" in buttons


def test_preference_questions_rooms_complex_payment(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, buttons = _say(engine, store, "WANT_START")
    assert out[0].text.startswith("Хэдэн өрөө") and "WANTR_parking" in buttons
    out, buttons = _say(engine, store, "WANTR_3")
    assert buttons == ["WANTC_gv", "WANTC_hn", "WANTC_any"]
    out, buttons = _say(engine, store, "WANTC_gv")
    assert buttons == ["WANTP_cash", "WANTP_loan", "WANTP_barter", "WANTP_any"]
    out, _ = _say(engine, store, "WANTP_barter")
    assert out[0].text.startswith("Таны сонголт: 3 өрөө · Гэрлүг Виста · Бартер.")
    found = [load_catalog(BIZ).by_sku[c.buttons[0].payload[5:]] for c in _cards(out)]
    assert found and all(p["rooms"] == 3 and p["area_id"] == "gerlug" and "barter" in p["pay"]
                         and available(p) for p in found)
    prices = [p["offers"]["sale"]["price_mnt"] for p in found]
    assert prices == sorted(prices)
    # nothing fits every answer: the closest, saying so
    for step in ("WANT_START", "WANTR_5", "WANTC_gv"):
        _say(engine, store, step)
    out, _ = _say(engine, store, "WANTP_barter")
    assert out[0].text.startswith("Яг таны сонголтоор") and _cards(out)


def test_a_unit_that_does_not_exist_says_not_found(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, _ = _say(engine, store, "Гэрлүг Виста 40-р байр 20 давхар 3 өрөө")
    assert out[0].text.startswith("Уучлаарай, «Гэрлүг Виста хотхон, 40-р байр, 20 давхарт 3 өрөө байр» "
                                  "манай мэдээлэлд олдсонгүй.")
    assert "төстэй" in out[0].text and _cards(out)[0].buttons[1].payload == "VIEW_GV02"


def test_browse_shows_only_available(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, buttons = _say(engine, store, "CAT")
    assert {b for b in buttons if b.startswith("CAT_")} == {"CAT_apartment", "CAT_parking"}
    out, _ = _say(engine, store, "CAT_parking")
    assert _cards(out) and all(available(load_catalog(BIZ).by_sku[c.buttons[0].payload[5:]])
                               for c in _cards(out))


def test_viewing_from_a_card_books_that_property(setup, store):
    engine, cal = setup
    _open_agency(engine, store)
    _, buttons = _say(engine, store, "VIEW_GV02")
    assert any(b.startswith("BDAY_") for b in buttons)            # straight to the day: no service step
    summary, done = _book_through(engine, store, buttons)

    assert "Гэрлүг Виста, 40-р байр, 3 өрөө" in summary and "40-р байр" in done
    assert cal.calendars == ["Өргөө Хаус үл хөдлөх хөрөнгө · Ajilt-AI демо"]
    assert [e for _, e in cal.shared] == ["a@example.com", "b@example.com"]
    (event,) = cal.events
    assert event["summary"].startswith("Байр үзэх: Гэрлүг 3 өрөө GV02 — Бат-Эрдэнэ")
    assert event["location"].startswith("Хан-Уул дүүрэг, 18-р хороо, Е-мартын урд, Гэрлүг Виста")
    assert "GV02" in event["description"] and event["private"]["item"] == "GV02"
    assert event["end"] - event["start"] == timedelta(minutes=45)
    with store._conn() as c:
        row = c.execute("SELECT * FROM bookings").fetchone()
    assert row["business_id"] == BIZ and row["service_id"] == "viewing" and row["event_id"] == "ev1"


def test_book_button_asks_which_property(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, buttons = _say(engine, store, "BOOK")
    assert out[-1].text.startswith("Аль байрыг")
    views = [b for b in buttons if b.startswith("VIEW_")]
    assert views and all(available(load_catalog(BIZ).by_sku[b[5:]]) for b in views)   # never sold ones
    assert "BOOK_CONSULT" in buttons and len(buttons) <= 13

    _say(engine, store, "Гэрлүг Виста 40-р байр 5 давхар 3 өрөө")   # one card shown...
    out, buttons = _say(engine, store, "BOOK")                     # ...so that one is booked
    assert any(b.startswith("BDAY_") for b in buttons)


def test_consultation_happens_at_the_office(setup, store):
    engine, cal = setup
    _open_agency(engine, store)
    _, buttons = _say(engine, store, "BOOK_CONSULT")
    summary, done = _book_through(engine, store, buttons)
    assert "Зөвлөгөө" in summary and "Их тойруу 21" in done
    assert cal.events[0]["location"].startswith("Сүхбаатар дүүрэг, 8-р хороо, Их тойруу 21")


def test_llm_gets_an_index_and_details_of_what_is_shown(store, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "BASMN_API_KEY", "")
    llm = ScriptedLLM("Тийм, GV02-ийг үзэх цаг товлоё. [BOOK]")
    engine = DemoEngine(llm=llm, store=store, calendar=FakeCalendar())
    _open_agency(engine, store)
    out, buttons = _say(engine, store, "Гэрлүг Виста 40-р байр 5 давхар 3 өрөө очиж үзмээр байна")
    system = llm.prompts[-1][0]["content"]
    index = system.split("LISTINGS IN THESE PLACES (one line each):\n")[1].split("\n\n")[0].splitlines()
    assert len(index) == 104                                     # both complexes; other places as summary
    assert "  Zaisan (Khan-Uul): " in system and "  13th microdistrict (Bayanzurkh): " in system
    assert "GV01 SOLD | Gerlug Vista, bldg 40 floor 9 of 16 | 3 rooms 78.03 m² | sale 684M (8.77M/m²) cash,loan,barter" in index
    assert "Gerlug Vista complex (" in system and "Hunnu 2222 complex (" in system
    assert "GV02 | AVAILABLE" in system and "FOR SALE 664,000,000 MNT" in system
    assert "floor 5 of 16 (in Mongolian write «16/5 давхарт»)" in system
    assert "shown as picture cards under your reply: GV02" in system
    assert "how they plan to pay (cash, bank loan or mortgage, or trade-in/barter)" in system
    assert len(system) < 30_000                                  # an index, not every detail
    assert out[0].text == "Тийм, GV02-ийг үзэх цаг товлоё."
    assert any(b.startswith("BDAY_") for b in buttons)            # booking GV02 straight away

    _say(engine, store, "MENU")
    _open_agency(engine, store)
    _say(engine, store, "Гэрлүг Виста 40-р байр 9 давхар 3 өрөө")
    system = llm.prompts[-1][0]["content"]
    assert "ALTERNATIVES: GV02 (same building, floor 5 of 16), GV21 (same complex, Gerlug Vista, bldg 39" in system
    assert "\nGV21 | AVAILABLE" in system                         # an alternative's details too


def test_llm_is_told_what_was_not_found(store, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "BASMN_API_KEY", "")
    llm = ScriptedLLM("Хамгийн ойр нь 40-р байрны 5 давхарт 3 өрөө байна.")
    engine = DemoEngine(llm=llm, store=store, calendar=FakeCalendar())
    _open_agency(engine, store)
    out, _ = _say(engine, store, "gerlug vista 40r bair 20 dawhar 3 uruu bga yu")
    system = llm.prompts[-1][0]["content"]
    assert "NOT FOUND: the customer asked about a 3-room flat on floor 20 in Gerlug Vista complex, bldg 40" in system
    assert out[0].text == ("Уучлаарай, «Гэрлүг Виста хотхон, 40-р байр, 20 давхарт 3 өрөө байр» манай "
                           "мэдээлэлд олдсонгүй.\n\nХамгийн ойр нь 40-р байрны 5 давхарт 3 өрөө байна.")


def test_wholesale_catalog_is_unchanged():
    catalog = load_catalog("wholesale")
    p = catalog.by_sku["MCC001"]
    assert catalog.card(p, "mn", "").buttons[0].payload == "ORDER_MCC001"
    assert "PRODUCT CATALOG: 380 products" in catalog.prompt_context([p], "en")
    assert re.search(r"≈ [\d,]+₮", catalog.card(p, "mn", "").subtitle)


def test_llm_offering_a_viewing_does_not_start_booking(store, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "BASMN_API_KEY", "")
    llm = ScriptedLLM("GV01 зарагдсан, GV02 боломжтой. GV02-ийг үзэх цаг товлох уу? [BOOK]")
    engine = DemoEngine(llm=llm, store=store, calendar=FakeCalendar())
    _open_agency(engine, store)
    out, buttons = _say(engine, store, "Гэрлүг Виста 40-р байр 9 давхар 3 өрөө байна уу?")
    assert out[0].text.endswith("товлох уу?") and "[BOOK]" not in out[0].text
    assert not any(b.startswith("BDAY_") for b in buttons)            # no booking without a yes
    assert "яг тэр байранд" in out[1].text                              # the sold one's alternatives


def test_a_question_during_booking_leaves_it(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    _, buttons = _say(engine, store, "VIEW_GV02")
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
    _say(engine, store, "VIEW_GV02")
    out, _ = _say(engine, store, "INFO_GV12")
    assert "GV12" in out[0].text and store.get_session("u1", "web").state == "CHAT"


def test_numbered_answer_still_continues_the_booking(setup, store):
    """ZevChat and others answer with the option's number; that is not a new question."""
    engine, _ = setup
    _open_agency(engine, store)
    _say(engine, store, "VIEW_GV02")
    out, buttons = _say(engine, store, "1")
    assert any(b.startswith("BTIME_") for b in buttons)


def test_this_one_means_the_listing_last_opened(store, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "BASMN_API_KEY", "")
    llm = ScriptedLLM("Тийм, 8%-ийн ипотекоор авч болно.")
    engine = DemoEngine(llm=llm, store=store, calendar=FakeCalendar())
    _open_agency(engine, store)
    _say(engine, store, "Гэрлүг Виста 6 өрөө")             # earlier talk about another listing
    _say(engine, store, "VIEW_GV02")                        # then a card's booking button
    out, _ = _say(engine, store, "Энэ байр ипотекоор авч болох уу?")
    system = llm.prompts[-1][0]["content"]
    assert "now looking at GV02" in system and "\nGV02 | AVAILABLE" in system
    assert [c.buttons[0].payload for c in _cards(out)] == ["INFO_GV02"]
    assert store.get_session("u1", "web").state == "CHAT"   # the question left the booking


def test_a_general_question_shows_no_cards(setup, store):
    engine, _ = setup
    _open_agency(engine, store)
    out, _ = _say(engine, store, "Байр үзэхэд төлбөртэй юу?")
    assert _cards(out) == []
    assert out[0].text.startswith("Үгүй, байр үзэх")                     # the FAQ answer


@pytest.mark.parametrize("query, expected", [
    ("Гэрлүг Виста хотхоны 40-р байрны 9 давхрын 3 өрөө байр", "GV01"),
    ("gerlug vista 40r bair 9 dawhar 3 uruu", "GV01"),
    ("Хүннү 2222 5-р байр 9 давхар", "HN03"),
    ("hunnu 10r bair 21 davhar 5 uruu", "HN01"),
])
def test_a_unit_named_by_block_and_floor_is_found_even_when_gone(query, expected):
    assert [p["sku"] for p in load_catalog(BIZ).search(query)] == [expected]


def test_a_neighbourhood_question_puts_its_listings_in_the_index(store, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "BASMN_API_KEY", "")
    llm = ScriptedLLM("Зайсанд 3 өрөө байр байна.")
    engine = DemoEngine(llm=llm, store=store, calendar=FakeCalendar())
    _open_agency(engine, store)
    out, _ = _say(engine, store, "Зайсанд 3 өрөө байр байгаа юу")
    system = llm.prompts[-1][0]["content"]
    index = system.split("LISTINGS IN THESE PLACES (one line each):\n")[1].split("\n\n")[0].splitlines()
    zaisan = [p["sku"] for p in load_catalog(BIZ).products if p["area_id"] == "zaisan"]
    assert len(index) == 104 + len(zaisan) and all(any(l.startswith(s + " ") for l in index) for s in zaisan)
    assert _cards(out) and len(system) < 30_000
