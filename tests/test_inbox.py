"""CRM inbox: messages are logged, a person can take over and hand back.

    python -m pytest tests
"""
import pytest
from fastapi.testclient import TestClient

from app import main
from app.store import Store

STAFF = {"X-Staff-Token": "staff-s3cret"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    s = Store(str(tmp_path / "test.db"))
    monkeypatch.setattr(main, "store", s)
    monkeypatch.setattr(main.engine, "store", s, raising=False)
    monkeypatch.setattr(main.engine.booking, "store", s)
    monkeypatch.setattr(main.settings, "STAFF_API_TOKEN", "staff-s3cret")
    monkeypatch.setattr(main.settings, "LLM_ENABLED", False, raising=False)
    return TestClient(main.app), s


def chat(c, text, session="inboxtest01"):
    return c.post("/api/chat", json={"session": session, "message": text}).json()["messages"]


def test_messages_logged(client):
    c, s = client
    chat(c, "MENU_CONTACT")
    rows = s.messages_after("web-inboxtest01", 0, authors=("patient", "bot"))
    assert rows[0]["author"] == "patient" and rows[1]["author"] == "bot"
    assert s.get_conversation("web-inboxtest01")["last_preview"]


def test_human_takes_over_and_releases(client):
    c, s = client
    chat(c, "MENU_HUMAN")
    conv = s.get_conversation("web-inboxtest01")
    assert conv["needs_human"] == 1
    assert chat(c, "сайн уу") == []                     # bot is quiet

    r = c.post("/api/staff/reply", headers=STAFF,
               json={"sender_id": "web-inboxtest01", "channel": "web", "text": "Сайн байна уу, би Сараа", "staff_user_id": 3})
    assert r.status_code == 200
    assert s.get_conversation("web-inboxtest01")["needs_human"] == 0
    up = c.get("/api/chat/updates", params={"session": "inboxtest01", "since": 0}).json()["messages"]
    assert [m["text"] for m in up] == ["Сайн байна уу, би Сараа"]
    assert c.get("/api/chat/updates", params={"session": "inboxtest01", "since": up[-1]["id"]}).json()["messages"] == []

    c.post("/api/staff/release", headers=STAFF, json={"sender_id": "web-inboxtest01"})
    assert chat(c, "MENU_CONTACT")                       # bot answers again


def test_staff_api_needs_token(client):
    c, _ = client
    assert c.post("/api/staff/reply", json={"sender_id": "x", "channel": "web", "text": "hi"}).status_code == 403
    assert c.post("/api/staff/reply", headers={"X-Staff-Token": "nope"},
                  json={"sender_id": "x", "channel": "web", "text": "hi"}).status_code == 403
