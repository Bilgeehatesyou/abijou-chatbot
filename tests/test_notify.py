"""Telegram alert when a meeting with Ajilt-AI is booked: chatbot (any channel) and
the website form send one; demo businesses' bookings and a missing token don't;
a Telegram failure never breaks the booking."""
from datetime import datetime, timedelta

import httpx
import pytest

from app import meetings, notify
from app.booking import BookingFlow, ajilt_ai_business, local_tz
from app.config import settings
from app.store import Store


class FakeTelegram:
    def __init__(self, status=200):
        self.sent, self.status = [], status

    def __call__(self, url, json=None, timeout=None, **kw):
        assert url == "https://api.telegram.org/bottest-token/sendMessage"
        self.sent.append(json)
        return httpx.Response(self.status, json={"ok": self.status == 200})


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "t.db"))


@pytest.fixture
def tg(monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setattr(notify.httpx, "post", fake)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setattr(settings, "BASMN_API_KEY", "")
    return fake


def _book(store, biz, channel="instagram", sid="u1"):
    """Walk the chatbot booking flow to the end, always taking the first option."""
    flow = BookingFlow(store)
    session = store.get_session(sid, channel)
    session.channel = channel
    msgs, done = flow.start(session, "mn", biz)
    answers = {"BOOK_NAME": "Бат-Эрдэнэ", "BOOK_PHONE": "99112233", "BOOK_CONFIRM": "BOK"}
    for _ in range(12):
        if done:
            return msgs
        text = answers.get(session.state) or next(
            q.payload for m in msgs for q in (m.quick_replies or []) if q.payload != "BCANCEL")
        msgs, done = flow.handle(session, "mn", biz, text)
    raise AssertionError(f"booking never finished (state {session.state})")


def test_chatbot_meeting_with_ajilt_ai_alerts(store, tg):
    _book(store, ajilt_ai_business(), channel="instagram")
    (msg,) = tg.sent
    assert msg["chat_id"] == "12345"
    text = msg["text"]
    assert "Шинэ уулзалт" in text and "Суваг: Instagram" in text
    assert "Нэр: Бат-Эрдэнэ" in text and "Утас: 99112233" in text
    assert "Google Calendar-т орсонгүй" in text      # no calendar in this test


def test_demo_business_booking_does_not_alert(store, tg):
    flow = BookingFlow(store)
    demo_id = next(b for b in flow.configs if b != "ajilt_ai")
    _book(store, {"id": demo_id, "name_mn": demo_id, "profile": {"phone": ""}}, channel="messenger")
    assert tg.sent == []


def test_website_form_alerts(store, tg):
    start = (datetime.now(local_tz()) + timedelta(days=3)).replace(hour=14, minute=0)
    meetings.create(store, None, {
        "type": "online", "date": f"{start:%Y-%m-%d}", "time": "14:00", "name": "Сараа",
        "phone": "88112233", "email": "saraa@example.com", "business": "Номин", "plan": "pro",
    })
    (msg,) = tg.sent
    text = msg["text"]
    assert "Суваг: Вэбсайт маягт" in text and "Онлайн уулзалт" in text
    assert f"{start:%Y-%m-%d}" in text and "14:00" in text
    assert "И-мэйл: saraa@example.com" in text and "Сонирхсон багц: pro" in text


def test_no_token_no_alert(store, tg, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    _book(store, ajilt_ai_business())
    assert tg.sent == []


def test_token_is_hidden_in_httpx_logs(monkeypatch, caplog):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123:secret")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "12345")
    # A real httpx client (so httpx writes its usual request log) that never leaves the machine.
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    monkeypatch.setattr(notify.httpx, "post",
                        lambda url, **kw: httpx.Client(transport=transport).post(url, **kw))
    with caplog.at_level("INFO", logger="httpx"):
        assert notify.send("hi")
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "sendMessage" in logged and "123:secret" not in logged and "bot***" in logged


def test_telegram_failure_keeps_the_booking(store, tg, monkeypatch):
    def boom(*a, **kw):
        raise httpx.ConnectTimeout("down")
    monkeypatch.setattr(notify.httpx, "post", boom)
    out = _book(store, ajilt_ai_business())
    assert out and store.list_meetings()
