import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from v2 import fetch
from v2.schedule import DATA, Route, routes, selection
from v2.source.bio_se import fetch as bio


def test_registry_has_one_unique_route_per_cinema():
    all_routes = routes()
    for path in (DATA / "schema" / "MovieTheater").glob("*.jsonld"):
        assert len(json.loads(path.read_bytes())["identifier"]) == 1, path
    assert all_routes["Biocafé Tellus"].venue_id == "5abe9f74b43fc5a465bff57e"
    assert all_routes["Aveny Ludvika"].venue_id == "ncg23111"
    assert all_routes["Biostaden Eskilstuna"].venue_id == "3"
    assert all_routes["Cinemascenen (Hudiksvall)"].venue_id == "hudiksvall"
    assert all_routes["Ale Medborgarhusets Bio"] == Route("Ale Medborgarhusets Bio", "bio_se", "16484")
    assert all_routes["Biograf Odeon"].adapter == "kulturiskovde_se"
    assert all_routes["Ulricehamn Folkan"].adapter == "bio_se"
    assert "Folketshus" not in all_routes
    for route in all_routes.values():
        if route.adapter in fetch.SINGLE:
            assert route.venue_id == fetch.SINGLE[route.adapter]


def test_fetch_limits_bio_programmes_and_saves_selection(tmp_path, monkeypatch):
    requested = []

    def capture_json(session, url, path, *, body=None):
        if body is None:
            return {"cinemas": [{"id": 16484}, {"id": 16485}]}
        requested.append(body)
        return {}

    monkeypatch.setattr(bio, "capture_json", capture_json)
    monkeypatch.setattr(bio, "_venue", lambda cinema: SimpleNamespace(city="Alafors", name="Biograf"))
    monkeypatch.setattr(fetch._http, "session", lambda: nullcontext(SimpleNamespace(headers={})))
    route = routes()["Ale Medborgarhusets Bio"]
    result = fetch.capture(tmp_path, [route])

    assert requested == [{"cinemaId": 16484}]
    assert selection(result / "sources" / "bio_se") == [
        {"cinema": route.cinema, "adapter": "bio_se", "venue_id": "16484"}
    ]


def test_missing_or_duplicate_schedule_bindings_are_rejected(tmp_path):
    path = tmp_path / "schema" / "MovieTheater" / "Biograf.jsonld"
    path.parent.mkdir(parents=True)
    path.write_text('{"identifier": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="expected exactly one schedule identifier"):
        routes(tmp_path)

    raw = '{"identifier": [{"propertyID": "allabiografer:schedule:bio_se", "value": "42"}]}'
    path.write_text(raw, encoding="utf-8")
    path.with_name("Annan.jsonld").write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate schedule binding"):
        routes(tmp_path)
