"""nortic.se payload parsing."""

import json
from pathlib import Path

import pytest

from parse.parsers import nortic_se
from store import Film, Screening, Venue

_FIXTURE = Path(__file__).parent / "fixtures" / "nortic_se" / "shows.json"


@pytest.fixture(autouse=True)
def _no_tmdb(monkeypatch):
    monkeypatch.setattr(nortic_se, "_tmdb", lambda title: None)


@pytest.fixture
def items() -> list[Screening | Venue | Film]:
    return list(nortic_se._parse_payload(json.loads(_FIXTURE.read_text())))


def test_missing_arena_address_becomes_empty_string(items):
    venue = next(v for v in items if isinstance(v, Venue) and v.name == "Folketshus")
    assert venue.address == ""


def test_film_category_is_ingested(items):
    tellus = [s for s in items if isinstance(s, Screening) and s.cinema_name == "Biocafé Tellus"]
    assert len(tellus) == 2
    assert {s.title for s in tellus} == {"Tony"}


def test_non_film_categories_are_skipped(items):
    assert not any("Nyårskonsert" in getattr(i, "title", "") for i in items)
    assert not any(getattr(i, "name", "") == "Grand Hotell Spegelsalen" for i in items)


def test_screening_fields(items):
    s = next(s for s in items if isinstance(s, Screening) and s.title == "Biodlaren")
    assert s.city == "Askersund"
    assert s.cinema_name == "Sjöängen, Stora salongen"
    assert s.date.isoformat() == "2026-09-29"
    assert s.time.strftime("%H:%M") == "16:30"
    assert s.ticket_url == "https://tickets.nortic.se/ticket/show/357605"
    assert s.film_key == "nortic_se:biodlaren"


def test_film_metadata(items):
    film = next(f for f in items if isinstance(f, Film) and f.title == "Tony")
    assert film.key == "nortic_se:tony"
    assert film.source == "nortic_se"
    assert film.overview.startswith("En 19-årig Anthony Bourdain reser till Provincetown")
    assert "<p>" not in film.overview
    assert film.url == "https://tickets.nortic.se/ticket/event/86718"
    # The API's images are 16:9 event banners, not posters.
    assert film.poster_url == ""


def test_short_description_is_the_overview_fallback(items):
    film = next(f for f in items if isinstance(f, Film) and f.title == "Biodlaren")
    assert film.overview == "Ett utforskande av kärleken, naturen och livets cykler."


def test_one_film_per_title_merged_across_organizers(items):
    films = [f for f in items if isinstance(f, Film) and f.title == "Biodlaren"]
    assert len(films) == 1
    # Runtime comes from the second organizer's event; the first has none.
    assert films[0].runtime == 110


def test_every_screening_carries_its_film_key(items):
    keys = {f.key for f in items if isinstance(f, Film)}
    screenings = [s for s in items if isinstance(s, Screening)]
    assert screenings
    assert all(s.film_key in keys for s in screenings)
