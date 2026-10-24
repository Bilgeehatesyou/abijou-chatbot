"""The industry menu fits ManyChat's 11 quick replies, and every demo business is complete."""
import json
from pathlib import Path

import pytest
import yaml

from app import demo_data
from app.demo import DemoEngine
from app.llm import NullLLM
from app.store import Store

from test_real_estate import FakeCalendar


@pytest.fixture
def engine(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "BASMN_API_KEY", "")
    store = Store(str(tmp_path / "t.db"))
    demo_data.sync_businesses(store)
    return DemoEngine(llm=NullLLM(), store=store, calendar=FakeCalendar()), store


def _say(engine, store, text):
    s = store.get_session("u1", "web")
    s.channel = "web"
    out = engine.handle(s, text)
    return [q.payload for m in out for q in (m.quick_replies or [])]


def test_menu_pages_fit_and_reach_every_industry(engine):
    eng, store = engine
    first = _say(eng, store, "")
    second = _say(eng, store, "IND_MORE")
    assert len(first) <= 11 and len(second) <= 11
    assert "IND_MORE" in first and "IND_BACK" in second
    shown = {b[4:] for b in first + second if b.startswith("IND_") and b not in ("IND_MORE", "IND_BACK")}
    assert shown == {i["id"] for i in demo_data.load_seeds()["industries"]}
    assert _say(eng, store, "IND_BACK") == first


@pytest.mark.parametrize("typed, business", [("фитнес", "fitness"), ("уул уурхай", "mining"),
                                             ("ресторан", "restaurant"), ("аялал", "travel")])
def test_typed_industry_opens_its_business(engine, typed, business):
    eng, store = engine
    _say(eng, store, "")
    _say(eng, store, typed)
    assert store.get_session("u1", "web").data.get("biz") == business


def test_every_seeded_business_has_data_and_a_tour():
    seeds = demo_data.load_seeds()
    tours = yaml.safe_load(Path("data/demo/tours.yaml").read_text(encoding="utf-8"))
    industries = {i["id"] for i in seeds["industries"]}
    for seed in seeds["businesses"]:
        biz = json.loads((demo_data.BUSINESS_DIR / f"{seed['id']}.json").read_text(encoding="utf-8"))
        assert biz["industry"] == seed["industry"] in industries
        assert seed["id"] in tours["businesses"] and seed["industry"] in tours["industries"]
        if "ajiltai.tech demo" in biz["generated_with"]:
            assert not demo_data.consistency_warnings(biz)
