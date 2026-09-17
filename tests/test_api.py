"""Tests for the HTTP surface.

The engine is covered by ``test_model.py``; these cover the seam around it --
routing, query parsing, and above all the error sentences. Those sentences are
shown verbatim in the dashboard to whoever typed the bad input, so each one is
pinned here.

``TestClient`` drives the real application in-process, so nothing binds a port.
"""

import json

import pytest
from fastapi.testclient import TestClient

from autopricer.api import create_app
from autopricer.settings import Settings
from autopricer.state import AppState


@pytest.fixture(scope="module")
def state():
    return AppState()


@pytest.fixture(scope="module")
def client(state):
    return TestClient(create_app(Settings(), state=state))


@pytest.fixture(scope="module")
def game(state):
    """A game that has both a board and sales."""
    return state.fit.snap.events[len(state.fit.snap.events) // 2].key


# ---------------------------------------------------------------- configuration
def test_settings_default_to_the_laptop_case():
    s = Settings.from_env({})
    assert (s.host, s.port) == ("127.0.0.1", 8765)
    assert s.reload_token is None and s.cors_origins == ()
    assert (s.data_dir / "listings.tsv").is_file()
    assert (s.web_dir / "index.html").is_file()


def test_settings_come_from_the_environment():
    s = Settings.from_env({
        "AUTOPRICER_HOST": "0.0.0.0",
        "AUTOPRICER_PORT": "9000",
        "AUTOPRICER_CORS_ORIGINS": "https://a.example, https://b.example",
        "AUTOPRICER_RELOAD_TOKEN": "t",
        "AUTOPRICER_LOG_LEVEL": "WARNING",
        "AUTOPRICER_DATA_DIR": "/mnt/snapshot",
        # An unprefixed variable is not ours.
        "PORT": "1234",
    })
    assert (s.host, s.port) == ("0.0.0.0", 9000)
    assert s.cors_origins == ("https://a.example", "https://b.example")
    assert s.reload_token == "t"
    assert s.log_level == "warning"  # uvicorn wants it lower-cased
    assert str(s.data_dir) == "/mnt/snapshot"


# ------------------------------------------------------------------- the pages
def test_dashboard_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<title>" in r.text
    assert '/static/app.js' in r.text


def test_static_assets_are_served(client):
    r = client.get("/static/app.js")
    assert r.status_code == 200
    assert "async function api(" in r.text


def test_the_ui_has_no_second_engine(client):
    """The dashboard once shipped a JavaScript mirror of the Python model for a
    standalone build. There is one implementation now; a reintroduced fallback
    would drift from Python silently, which is exactly what happened before."""
    app_js = client.get("/static/app.js").text
    assert "AUTOPRICER_LOCAL" not in app_js
    assert "AUTOPRICER_BUNDLE" not in app_js
    assert client.get("/static/engine.js").status_code == 404


def test_health_reports_the_loaded_snapshot(client):
    body = client.get("/health").json()
    assert body["ok"] is True
    snap = body["snapshot"]
    assert snap["generation"] >= 1
    assert snap["events"] == 35
    assert snap["listings"] > 9_000
    assert snap["loaded_at"].startswith("20")


# -------------------------------------------------------------------- payloads
def test_meta_carries_what_the_ui_needs_to_boot(client):
    m = client.get("/api/meta").json()
    assert m["venue"] == "Target Center"
    assert len(m["events"]) == m["counts"]["events"] == 35
    assert m["default_strategy"] in m["strategies"]
    assert m["sections"], "the section datalist would be empty"
    assert 0.5 < m["clearing_ratio"] < 1.0


@pytest.mark.parametrize("path", [
    "/api/meta", "/api/overview", "/api/map", "/api/model",
    "/api/sales", "/api/listings",
])
def test_unscoped_endpoints_answer(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert r.json()


@pytest.mark.parametrize("path", ["/api/sales", "/api/listings"])
def test_scoping_to_one_game_narrows_the_payload(client, game, path):
    allg = client.get(path, params={"event": "all"}).json()
    one = client.get(path, params={"event": game}).json()
    assert allg["scope"] == "all"
    assert one["scope"] == game
    assert len(one["sections"]) <= len(allg["sections"])


def test_section_detail(client, game):
    body = client.get("/api/section/112", params={"event": game}).json()
    assert body["section"] == "112"
    assert body["tier"] == "lower"
    assert body["scope"] == game


def test_dates_survive_serialisation(client):
    """Sales carry ``datetime.date``, which plain ``json.dumps`` cannot
    encode -- the response class passes ``default=str``. Without it every
    payload touching an invoice date would 500."""
    body = client.get("/api/sales", params={"event": "all"}).json()
    days = [d for s in body["sections"] for d in s.get("by_day", [])]
    assert body["by_day"] or days or body["totals"]["sales"] == 0
    assert json.dumps(body)  # round-trips as plain JSON


# ---------------------------------------------------------------------- quotes
def test_a_quote_names_the_game_it_priced(client, game):
    q = client.get("/api/price", params={
        "event": game, "section": "112", "row": "C", "qty": 2,
    }).json()
    assert q["request"]["event"] == game
    assert q["request"]["section"] == "112"
    assert q["request"]["row"] == "C"
    assert q["recommendation"]["price"] > 0


def test_strategy_ladder_is_ordered(client, game):
    prices = {}
    for s in ("aggressive", "balanced", "patient"):
        q = client.get("/api/price", params={
            "event": game, "section": "112", "row": "C", "strategy": s,
        }).json()
        assert q["request"]["strategy"] == s
        prices[s] = q["recommendation"]["price"]
    assert prices["aggressive"] <= prices["balanced"] <= prices["patient"]


def test_qty_defaults_and_floors_at_one(client, game):
    base = {"event": game, "section": "112", "row": "C"}
    assert client.get("/api/price", params=base).json()["request"]["qty"] == 2
    assert client.get("/api/price", params={**base, "qty": "0"}) \
        .json()["request"]["qty"] == 1


# ------------------------------------------------ the sentences the UI displays
@pytest.mark.parametrize("params,message", [
    ({"section": "112"},
     "event and section are required"),
    ({"event": "2026-12-25"},
     "event and section are required"),
    ({"event": "1999-01-01", "section": "112"},
     "unknown event '1999-01-01'"),
    ({"event": "2026-12-25", "section": "999"},
     "'999' is not a Target Center seat section"),
    ({"event": "2026-12-25", "section": "112", "qty": "abc"},
     "qty must be a whole number, got 'abc'"),
    ({"event": "2026-12-25", "section": "112", "strategy": "yolo"},
     "unknown strategy 'yolo'; expected one of "
     "['aggressive', 'balanced', 'patient']"),
])
def test_bad_input_returns_400_and_a_readable_sentence(client, params, message):
    r = client.get("/api/price", params=params)
    assert r.status_code == 400
    assert r.json() == {"error": message}


def test_unknown_event_on_a_view_is_also_a_400(client):
    r = client.get("/api/listings", params={"event": "1999-01-01"})
    assert r.status_code == 400
    assert r.json()["error"] == "unknown event '1999-01-01'"


def test_unknown_section_on_a_view_is_also_a_400(client):
    r = client.get("/api/section/999")
    assert r.status_code == 400
    assert r.json()["error"] == "'999' is not a Target Center seat section"


def test_unknown_route_is_a_json_404(client):
    r = client.get("/api/nope")
    assert r.status_code == 404
    assert r.json() == {"error": "not found"}


def test_static_path_traversal_is_refused(client):
    r = client.get("/static/../autopricer/config.py")
    assert r.status_code in (400, 404)
    assert "ModelParams" not in r.text


# ---------------------------------------------------------------------- reload
def test_reload_is_off_unless_a_token_is_configured(client):
    r = client.post("/api/reload")
    assert r.status_code == 503
    assert "AUTOPRICER_RELOAD_TOKEN" in r.json()["error"]


def test_reload_needs_the_token_and_then_refits():
    state = AppState()
    app = create_app(Settings(reload_token="s3cret"), state=state)
    c = TestClient(app)

    assert c.post("/api/reload").status_code == 403
    assert c.post("/api/reload",
                  headers={"X-Autopricer-Token": "wrong"}).status_code == 403

    before = state.fit.generation
    r = c.post("/api/reload", headers={"X-Autopricer-Token": "s3cret"})
    assert r.status_code == 200
    assert r.json()["snapshot"]["generation"] == before + 1


def test_a_reload_swaps_the_whole_bundle_at_once():
    """Views are memoised against the fit they were built from, so a refit
    must hand out a new bundle rather than mutate the live one -- otherwise a
    request in flight can mix new sales with an old model."""
    state = AppState()
    first = state.fit
    first.overview()
    state.reload()
    assert state.fit is not first
    assert state.fit.generation == first.generation + 1
    assert state.fit.overview() == first.overview()
