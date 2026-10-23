"""The AI sales agent at the front door: greeting, the conversation the model leads,
what it learns going onto the lead, phone numbers caught in chat, the meeting and
callback forms, and the demo still one tap away."""
import json

import pytest

from app.agent import SalesAgent, find_phone, parse_reply
from app.config import settings
from app.conversation import Engine
from app.demo import DemoEngine
from app.llm import NullLLM
from app.pricing import Pricing
from app.router import AppRouter
from app.store import Store
from tests.test_real_estate import FakeCalendar


class QueueLLM(NullLLM):
    """Replies from a list in order (None = the model failed); keeps every prompt."""

    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def chat(self, messages, temperature=0.3, timeout=None, **kw):
        self.prompts.append(messages)
        return self.replies.pop(0) if self.replies else None


def reply(text, **data):
    return f"{text}\n<data>{json.dumps(data, ensure_ascii=False)}</data>"


@pytest.fixture
def make(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "BASMN_API_KEY", "")

    def build(*replies):
        store = Store(str(tmp_path / "t.db"))
        llm = QueueLLM(*replies)
        demo = DemoEngine(llm=NullLLM(), store=store, calendar=FakeCalendar())
        pricing = Pricing(settings.PRICING_PATH)
        forms = Engine(llm=llm, pricing=pricing, store=store, booking=demo.booking)
        router = AppRouter(demo, SalesAgent(llm=llm, engine=forms, store=store, pricing=pricing), store)

        def say(text, sid="u1"):
            session = store.get_session(sid, "web")
            session.channel = "web"
            return router.handle(session, text), store.get_session(sid, "web")
        return say, llm, store
    return build


def payloads(msgs):
    return [q.payload for m in msgs for q in (m.quick_replies or [])]


def leads(store):
    with store._conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM leads ORDER BY id").fetchall()]


def test_opens_with_a_question_about_the_business_not_a_menu(make):
    say, llm, _ = make()
    out, s = say("HOME")
    assert "ямар үйл ажиллагаа" in out[0].text
    assert "MODE_SALES" not in payloads(out)         # no "pick Ajilt-AI or demo" menu any more
    assert payloads(out) == ["MODE_DEMO", "LANG_EN"]
    assert s.state == "CHAT" and s.data["_mode"] == "sales"
    assert not llm.prompts                            # the greeting doesn't wait for the model


def test_english_site_greets_in_english(make):
    say, _, _ = make()
    out, _ = say("LANG_EN")
    assert "What does your business do?" in out[0].text


def test_model_leads_and_what_it_learns_is_kept(make):
    say, llm, _ = make(
        reply("Шүдний эмнэлэг гэдэг сайхан! Цаг захиалгыг одоо хэн, яаж авдаг вэ?",
              industry="шүдний эмнэлэг", business_type="Services", buttons=[]),
        reply("Ойлголоо. Танд STARTER багц тохирно: сард 500,000₮.", employees=6,
              pains="оройн мессежид хариулж амждаггүй", plan="STARTER", buttons=["MEET", "DEMO"]),
    )
    say("HOME")
    out, s = say("Бид шүдний эмнэлэг")
    assert out[0].text.startswith("Шүдний эмнэлэг гэдэг")
    assert "<data>" not in out[0].text
    assert out[0].quick_replies is None               # still asking: no buttons pushed
    assert s.data["industry"] == "шүдний эмнэлэг" and s.data["business_type"] == "Services"

    out, s = say("6 хүнтэй, оройн мессежүүдэд хариулж чаддаггүй")
    assert payloads(out) == ["ACTION_BOOK", "MODE_DEMO"]
    assert s.data["employees"] == 6 and s.data["tier"] == "STARTER" and s.data["quote"] == 500000

    system = llm.prompts[-1][0]["content"]
    assert "шүдний эмнэлэг" in system                 # WHAT WE KNOW goes back to the model
    assert "STARTER 500,000₮" in system               # prices come from pricing.yaml
    history = llm.prompts[-1][1:]
    assert history[0]["role"] == "assistant" and "ямар үйл ажиллагаа" in history[0]["content"]
    assert history[-1] == {"role": "user", "content": "6 хүнтэй, оройн мессежүүдэд хариулж чаддаггүй"}


def test_question_as_the_first_message_is_answered_by_the_agent(make):
    say, llm, _ = make(reply("STARTER багц сард 500,000₮-өөс эхэлдэг. Танай бизнес юу хийдэг вэ?"))
    out, s = say("une hed ve")
    assert out[0].text.startswith("STARTER багц")
    assert s.data["_mode"] == "sales" and len(llm.prompts) == 1


def test_phone_in_chat_becomes_a_lead_with_what_the_agent_learned(make):
    say, llm, store = make(
        reply("Баярлалаа! Таныг хэн гэдэг вэ?", industry="кофе шоп",
              wants="Instagram захиалга", contact_name=None),
        reply("Баярлалаа, Болд!", contact_name="Болд"),
    )
    say("HOME")
    out, s = say("Миний дугаар 9911-2233, залгаарай")
    assert s.data["phone"] == "99112233"
    assert "99112233" in llm.prompts[0][0]["content"]   # the model is told it's saved
    rows = leads(store)
    assert len(rows) == 1 and rows[0]["phone"] == "99112233" and rows[0]["path"] == "callback"

    say("Болд")
    rows = leads(store)
    assert rows[-1]["contact_name"] == "Болд"           # the name joins the same number


@pytest.mark.parametrize("text, phone", [
    ("99112233", "99112233"), ("+976 8811 2233", "88112233"), ("утас: 9911 2233.", "99112233"),
    ("сард 50000000 ₮ орлоготой", None), ("12 ажилтан, 3 салбар", None), ("1500000", None),
])
def test_find_phone(text, phone):
    assert find_phone(text) == phone


def test_parse_reply_strips_the_data_block_even_when_broken():
    assert parse_reply('Сайн уу\n<data>{"plan": "PRO"}</data>') == ("Сайн уу", {"plan": "PRO"})
    assert parse_reply("**Сайн** уу\n<data>{oops") == ("Сайн уу", {})
    assert parse_reply("Зүгээр текст") == ("Зүгээр текст", {})
    assert parse_reply('Тийм\n```json\n{"buttons": ["DEMO"]}\n```') == ("Тийм", {"buttons": ["DEMO"]})


def test_model_down_still_offers_the_way_forward(make):
    say, _, _ = make(None)
    say("HOME")
    out, _ = say("Бид дэлгүүртэй")
    assert "8605 1688" in out[0].text
    assert payloads(out) == ["ACTION_CALLBACK", "ACTION_BOOK", "MODE_DEMO"]


def test_agreeing_to_meet_opens_the_calendar_then_returns_to_chat(make):
    say, _, store = make(reply("Гоё! Тохиромжтой өдрөө сонгоорой.", action="book",
                               industry="салон", pains="утсаар цаг авдаг"),
                         reply("Уулзъя! Өөр асуух зүйл байна уу?"))
    say("HOME")
    out, s = say("За уулзъя")
    assert s.state.startswith("BOOK_")
    assert any(p.startswith("BDAY_") or p.startswith("BSVC_") for p in payloads(out)), payloads(out)

    # cancel the form: back in the conversation, nothing pretends a meeting was booked
    out, s = say("BCANCEL")
    assert s.state == "CHAT" and s.data["industry"] == "салон"
    assert "(Уулзалт товлогдлоо.)" not in json.dumps(s.data["chat"], ensure_ascii=False)


def test_callback_button_asks_name_then_number(make):
    say, _, store = make(reply("Ойлголоо, PRO тохирно.", plan="PRO", wants="CRM",
                               buttons=["CALL"]))
    say("HOME")
    out, _ = say("50 ажилтантай")
    assert payloads(out) == ["ACTION_CALLBACK"]
    out, s = say("ACTION_CALLBACK")
    assert s.state == "ASK_CONTACT_NAME"
    say("Сараа")
    out, s = say("88112233")
    assert s.state == "CHAT" and s.data["wants"] == "CRM"
    row = leads(store)[-1]
    assert (row["contact_name"], row["phone"], row["tier"], row["quote"]) == ("Сараа", "88112233",
                                                                               "PRO", "1000000")


def test_a_question_while_we_wait_for_the_name_goes_to_the_agent(make):
    say, llm, _ = make(reply("Суурилуулалт 2,000,000₮ нэг удаа. Нэрээ хэлэх үү?"))
    say("HOME")
    say("ACTION_CALLBACK")
    out, s = say("суурилуулалт хэд вэ?")
    assert out[0].text.startswith("Суурилуулалт") and s.state == "CHAT"
    assert "contact_name" not in s.data


def test_demo_is_one_tap_away_and_home_comes_back_to_the_agent(make):
    say, _, _ = make()
    say("HOME")
    out, s = say("MODE_DEMO")
    assert s.data["_mode"] == "demo"
    out, s = say("HOME")
    assert s.data["_mode"] == "sales" and "ямар үйл ажиллагаа" in out[0].text


def test_no_leave_your_number_button_once_we_have_it(make):
    say, _, _ = make(reply("Баярлалаа!", buttons=["CALL", "DEMO"]))
    say("HOME")
    out, _ = say("99112233")
    assert payloads(out) == ["MODE_DEMO"]


def test_latin_mongolian_meeting_gets_a_mongolian_calendar(make):
    say, _, _ = make(reply("Тэгье! Доороос өдрөө сонгоорой.", action="book"))
    say("HOME")
    out, s = say("tiim ee uulzaya")
    assert s.state.startswith("BOOK_") and s.data["lang"] == "mn"
    assert "Cancel" not in " ".join(q.title for m in out for q in (m.quick_replies or []))


def test_coming_back_days_later_starts_fresh(make):
    say, _, store = make(reply("Ойлголоо."), reply("Сайн байна уу! Танай бизнес юу хийдэг вэ?"))
    say("HOME")
    say("ACTION_CALLBACK")                       # left half-way through the callback form
    with store._conn() as c:
        c.execute("UPDATE sessions SET updated_at = updated_at - 3 * 86400")
    out, s = say("hi")
    assert "ямар үйл ажиллагаа" in out[0].text   # the greeting, not "what's your name?"
    assert s.state == "CHAT" and "contact_name" not in s.data


def test_get_started_greets(make):
    say, _, _ = make()
    out, _ = say("Get Started")
    assert "ямар үйл ажиллагаа" in out[0].text


def test_first_message_is_read_as_the_answer_to_the_greeting(make):
    say, llm, _ = make(reply("Салон гэдэг сайхан! Цагаа яаж авдаг вэ?"))
    out, s = say("Бид салонтой")
    history = llm.prompts[0][1:]
    assert history[0]["role"] == "assistant" and "ямар үйл ажиллагаа" in history[0]["content"]
    assert history[-1]["content"] == "Бид салонтой"
    assert s.data["_mode"] == "sales" and s.state == "CHAT"


@pytest.mark.parametrize("words", ["bi shineer ehlii tehuu", "Шинээр эхэлье", "dahin ehleh", "restart pls"])
def test_start_over_words_leave_the_demo(make, words):
    say, _, _ = make()
    say("HOME")
    say("MODE_DEMO")
    out, s = say(words)
    assert s.data["_mode"] == "sales" and "ямар үйл ажиллагаа" in out[0].text


def test_a_quiet_demo_is_forgotten_after_half_an_hour(make):
    say, _, store = make(reply("Сайн байна уу! Танай бизнес юу хийдэг вэ?"))
    say("HOME")
    say("MODE_DEMO")
    with store._conn() as c:
        c.execute("UPDATE sessions SET updated_at = updated_at - 40 * 60")
    out, s = say("sain baina uu")
    assert s.data["_mode"] == "sales" and "ямар үйл ажиллагаа" in out[0].text
