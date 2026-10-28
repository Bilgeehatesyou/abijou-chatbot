"""Conversation tests with a fake model: no network, no Google, fresh SQLite per test.

    python -m pytest tests
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import booking as booking_mod
from app.booking import free_slots, normalize_phone
from app.bot import ClinicBot
from app.clinic import get_clinic
from app.lang import detect_lang
from app.llm import NullLLM
from app.models import Session
from app.store import Store


class FakeLLM(NullLLM):
    """Returns a canned reply and remembers the prompt it got."""

    def __init__(self, reply=None):
        self.reply = reply
        self.messages = None

    def chat(self, messages, **kw):
        self.messages = messages
        return self.reply


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "test.db"))


def make_bot(store, llm=None):
    return ClinicBot(llm=llm or NullLLM(), store=store, clinic=get_clinic())


def payloads(msgs):
    return [q.payload for m in msgs for q in (m.quick_replies or [])]


def say(bot, session, text):
    return bot.handle(session, text)


# ---- knowledge ----
def test_clinic_data_is_complete():
    c = get_clinic()
    assert len(c.branches) == 12
    assert {b["country"] for b in c.branches} == {"mn", "kr"}
    for item in c.services + c.branches + c.categories:
        for lang in ("mn", "en", "ko"):
            assert item["name"][lang], (item["id"], lang)
    for s in c.services:
        assert len(s["short"]["mn"]) <= 20 and len(s["short"]["ko"]) <= 20, s["id"]
        assert "MNT" in s["price"] and "KRW" in s["price"]
        assert s["category"] in {cat["id"] for cat in c.categories}
    for f in c.faqs:
        assert all(f["question"][x] and f["answer"][x] for x in ("mn", "en", "ko")), f["id"]
    assert len(c.services) <= 12      # 12 service buttons + cancel = Messenger's 13


def test_knowledge_has_the_clinic_texts():
    k = get_clinic().knowledge("mn")
    assert "NeoBeam" in k and "Gold PTT" in k and "Excel-V" in k and "Rejuran" in k
    assert "180,000₮" in k and "₩99,000" in k
    assert "Каннам" in k


# ---- language ----
@pytest.mark.parametrize("text,lang", [
    ("Сайн байна уу", "mn"), ("batga emchilgee une hed ve", "mn"),
    ("How much is NeoBeam?", "en"), ("여드름 치료 가격이 얼마예요?", "ko"), ("ok", None),
])
def test_detect_lang(text, lang):
    assert detect_lang(text) == lang


def test_korean_message_switches_buttons_to_korean(store):
    bot, s = make_bot(store), Session("u1")
    say(bot, s, "")
    out = say(bot, s, "안녕하세요 홍조 치료 하나요?")
    assert s.data["lang"] == "ko"
    assert any("예약" in q.title for m in out for q in (m.quick_replies or []))


def test_language_button_locks_language(store):
    bot, s = make_bot(store), Session("u1")
    out = say(bot, s, "LANG_EN")
    assert out[0].text.startswith("Hello")
    say(bot, s, "Сайн байна уу")
    assert s.data["lang"] == "en"


# ---- menus ----
def test_greeting_and_menus(store):
    bot, s = make_bot(store), Session("u1")
    out = say(bot, s, "GET_STARTED")
    assert "Abijou" in out[0].text
    assert {"BOOK", "MENU_SERVICES", "MENU_BRANCHES", "LANG_EN", "LANG_KO"} <= set(payloads(out))

    out = say(bot, s, "MENU_SERVICES")
    assert "CAT_acne" in payloads(out)
    out = say(bot, s, "CAT_acne")
    assert "NeoBeam" in out[0].text and "Gold PTT" in out[0].text
    assert "BOOKS_neobeam" in payloads(out)

    out = say(bot, s, "BRANCHES_kr")
    assert "Каннам" in out[0].text and "+82" in out[0].text
    assert "BOOKB_kr_gangnam" in payloads(out)


# ---- booking ----
def _book(bot, s, first, *steps):
    out = say(bot, s, first)
    for step in steps:
        out = say(bot, s, step(out) if callable(step) else step)
    return out


def first(prefix):
    return lambda out: next(p for p in payloads(out) if p.startswith(prefix))


def test_full_booking_in_korea(store):
    bot, s = make_bot(store), Session("u1", channel="instagram")
    say(bot, s, "GET_STARTED")
    out = _book(bot, s, "BOOKS_excel_v", "BCTRY_kr", "BBR_kr_gangnam",
                first("BDAY_"), first("BTIME_"), "Сараа", "010 1234 5678")
    assert s.state == "BOOK_CONFIRM"
    assert "₩120,000" in out[0].text and "Солонгосын цагаар" in out[0].text
    out = say(bot, s, "BOK")
    assert out[0].text.startswith("✅")
    assert s.state == "CHAT"

    rows = store.list_bookings()
    assert len(rows) == 1
    b = rows[0]
    assert (b["branch_id"], b["service_id"], b["currency"], b["price"]) == ("kr_gangnam", "excel_v", "KRW", 120000)
    assert b["phone"] == "010-1234-5678" and b["channel"] == "instagram"
    assert b["start_at"].endswith("+09:00")           # booked in Seoul time
    assert b["payment_status"] == "at_clinic"


def test_booking_from_branch_button_asks_service_first(store):
    bot, s = make_bot(store), Session("u1")
    out = say(bot, s, "BOOKB_ub_central")
    assert s.state == "BOOK_SERVICE"
    out = say(bot, s, "BSVC_neobeam")
    assert s.state == "BOOK_DAY"                       # branch already known
    assert "Улаанбаатарын цагаар" in out[0].text


def test_cancel_and_question_leave_booking(store):
    bot, s = make_bot(store), Session("u1")
    say(bot, s, "BOOK")
    assert s.state == "BOOK_SERVICE"
    out = say(bot, s, "Rejuran хэд вэ?")              # a question, not an answer
    assert s.state == "CHAT" and "Rejuran" in out[0].text
    say(bot, s, "BOOK")
    out = say(bot, s, "BCANCEL")
    assert s.state == "CHAT" and "цуцаллаа" in out[0].text


def test_capacity_blocks_a_full_slot(store, monkeypatch):
    clinic = get_clinic()
    branch = clinic.branch("ub_bayanzurkh")      # capacity 2
    tz = ZoneInfo("Asia/Ulaanbaatar")
    day = (datetime.now(tz) + timedelta(days=2)).date()
    while not branch["hours"].get(booking_mod.WEEKDAY_KEYS[day.weekday()]):
        day += timedelta(days=1)
    start = datetime.combine(day, datetime.strptime("11:00", "%H:%M").time(), tz)
    for i in range(branch["capacity"]):
        store.save_booking({"sender_id": f"x{i}", "channel": "web", "lang": "mn", "service_id": "neobeam",
                            "branch_id": "ub_bayanzurkh", "country": "mn", "start_at": start.isoformat(),
                            "end_at": (start + timedelta(minutes=30)).isoformat(), "name": "A", "phone": "99112233",
                            "price": 1, "currency": "MNT", "event_id": None, "calendar_status": "no_calendar"})
    bot = make_bot(store)
    busy = bot.booking._busy(branch, start - timedelta(hours=2), start + timedelta(hours=2))
    slots = free_slots(branch["hours"], day, 30, busy, datetime.now(tz), tz, branch["capacity"])
    assert start not in slots and start + timedelta(minutes=30) in slots
    store.set_booking_status(1, "cancelled")
    busy = bot.booking._busy(branch, start - timedelta(hours=2), start + timedelta(hours=2))
    assert start in free_slots(branch["hours"], day, 30, busy, datetime.now(tz), tz, branch["capacity"])


@pytest.mark.parametrize("raw,ok", [
    ("99112233", "99112233"), ("+976 9911 2233", "99112233"), ("010-1234-5678", "010-1234-5678"),
    ("+82 10 1234 5678", "010-1234-5678"), ("12345", None),
])
def test_phone_numbers(raw, ok):
    assert normalize_phone(raw) == ok


# ---- answers ----
def test_model_book_token_starts_booking_with_service_and_branch(store):
    llm = FakeLLM("Тэгье, цаг захиалъя. [BOOK:gold_ptt:kr_myeongdong]")
    bot, s = make_bot(store, llm), Session("u1")
    out = say(bot, s, "Мёндонд Gold PTT хийлгэмээр байна, цаг авъя")
    assert out[0].text == "Тэгье, цаг захиалъя."
    assert s.state == "BOOK_DAY"
    assert s.data["book"]["service"] == "gold_ptt" and s.data["book"]["branch"] == "kr_myeongdong"
    system = llm.messages[0]["content"]
    assert "gold_ptt" in system and "kr_myeongdong" in system and "NeoBeam" in system


def test_offer_with_question_mark_does_not_start_booking(store):
    bot, s = make_bot(store, FakeLLM("Цаг захиалах уу? [BOOK]")), Session("u1")
    say(bot, s, "Excel-V юу вэ")
    assert s.state == "CHAT"


def test_keyword_fallback_without_model(store):
    bot, s = make_bot(store), Session("u1")
    out = say(bot, s, "үрэвссэн батга эмчилдэг үү")
    assert "NeoBeam" in out[0].text
    out = say(bot, s, "엑셀V 가격")
    assert "₩120,000" in out[0].text
    out = say(bot, s, "tsag zahialmaar baina")
    assert s.state == "BOOK_SERVICE"
