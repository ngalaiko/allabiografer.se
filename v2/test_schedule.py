import json

import pytest

from v2.graph import DATA
from v2.pipeline import SINGLE
from v2.schedule import Route, routes


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
    for route in all_routes.values():
        if route.adapter in SINGLE:
            assert route.venue_id == SINGLE[route.adapter]


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
