"""CATALOG_SOURCE=db: the CRM's catalog rows over clinic.yaml.

    python -m pytest tests
"""
import copy

import pytest
from fastapi.testclient import TestClient

from app import clinic as clinic_mod, main
from app.clinic import get_clinic, overlay_catalog


def fake_rows(data):
    """CRM rows as import-catalog writes them, from clinic.yaml itself."""
    return {
        "countries": [{"id": c["id"], "name": c["name"], "tz": c["tz"], "currency": c["currency"]} for c in data["countries"]],
        "branches": [{"id": b["id"], "country_id": b["country"], "name": b["name"], "address": b.get("address"),
                      "hours_text": b.get("hours_text"), "note": b.get("note"), "phone": b.get("phone"), "hours": b["hours"],
                      "capacity": b.get("capacity", data.get("default_capacity", 1)), "active": True} for b in data["branches"]],
        "categories": [{"id": c["id"], "emoji": c.get("emoji"), "name": c["name"]} for c in data["categories"]],
        "services": [{"id": s["id"], "category_id": s.get("category"), "minutes": s["minutes"], "name": s["name"], "short": s["short"],
                      "details": s.get("details"), "price": dict(s["price"]), "price_note": s.get("price_note"),
                      "packages": s.get("packages", []), "options": s.get("options", []), "active": True} for s in data["services"]],
    }


@pytest.fixture
def yaml_data():
    clinic_mod._clinic, clinic_mod._yaml = None, None
    data = copy.deepcopy(get_clinic().data)
    yield data
    clinic_mod._clinic, clinic_mod._yaml = None, None


@pytest.fixture
def db_mode(monkeypatch, yaml_data):
    monkeypatch.setenv("CATALOG_SOURCE", "db")
    monkeypatch.setattr(clinic_mod, "_catalog_url", lambda: "postgresql://fake")
    clinic_mod._clinic = None
    return yaml_data


def test_overlay_changes_price_and_hides_inactive(yaml_data):
    rows = fake_rows(yaml_data)
    rows["services"][1]["price"]["KRW"] = 123000
    rows["services"][2]["active"] = False
    rows["branches"][0]["active"] = False
    out = overlay_catalog(yaml_data, rows)
    assert out["services"][0]["id"] == yaml_data["services"][0]["id"]
    svc = next(s for s in out["services"] if s["id"] == yaml_data["services"][1]["id"])
    assert svc["price"]["KRW"] == 123000
    assert yaml_data["services"][2]["id"] not in {s["id"] for s in out["services"]}
    assert yaml_data["branches"][0]["id"] not in {b["id"] for b in out["branches"]}
    # YAML-д л байгаа түлхүүрүүд үлдэнэ, FAQ хөндөгдөхгүй
    assert out["countries"][0]["flag"] == yaml_data["countries"][0]["flag"]
    assert out["faqs"] == yaml_data["faqs"]
    assert "KRW" in yaml_data["services"][1]["price"]


def test_unchanged_rows_give_the_same_catalog(yaml_data):
    out = overlay_catalog(yaml_data, fake_rows(yaml_data))
    for key in ("countries", "categories"):
        assert out[key] == yaml_data[key]
    for a, b in zip(out["services"], yaml_data["services"]):
        assert a == b


def test_api_catalog_shape_and_new_price(db_mode, monkeypatch):
    before = TestClient(main.app).get("/api/catalog").json()
    rows = fake_rows(db_mode)
    rows["services"][0]["price"]["MNT"] = 99000
    monkeypatch.setattr(clinic_mod, "load_catalog", lambda url: rows)
    clinic_mod._clinic = None
    after = TestClient(main.app).get("/api/catalog").json()
    assert after.keys() == before.keys()
    for k in after:
        if isinstance(after[k], list):
            assert [sorted(x) for x in after[k]] == [sorted(x) for x in before[k]]
    assert after["services"][0]["price"]["MNT"] == 99000


def test_db_error_falls_back_to_yaml(db_mode, monkeypatch, caplog):
    def boom(url):
        raise RuntimeError("db down")
    monkeypatch.setattr(clinic_mod, "load_catalog", boom)
    clinic_mod._clinic = None
    c = get_clinic()
    assert [s["id"] for s in c.services] == [s["id"] for s in db_mode["services"]]
    assert "db down" in caplog.text


def test_ttl_reload(db_mode, monkeypatch):
    rows = fake_rows(db_mode)
    calls = []
    monkeypatch.setattr(clinic_mod, "load_catalog", lambda url: calls.append(1) or rows)
    clinic_mod._clinic = None
    get_clinic(); get_clinic()
    assert len(calls) == 1
    monkeypatch.setattr(clinic_mod, "_loaded_at", clinic_mod._loaded_at - clinic_mod.CATALOG_TTL - 1)
    get_clinic()
    assert len(calls) == 2
