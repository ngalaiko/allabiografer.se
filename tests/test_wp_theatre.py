"""WordPress Theater production page parsing."""

from pathlib import Path

import pytest

from parse.parsers import wp_theatre
from store import Film

_FIXTURES = Path(__file__).parent / "fixtures" / "wp_theatre"
_SITE = {"city": "Göteborg", "name": "Capitol"}


@pytest.fixture(autouse=True)
def tmdb_calls(monkeypatch):
    calls: list[tuple[str, int | None]] = []
    monkeypatch.setattr(wp_theatre, "_tmdb", lambda title, runtime=None: calls.append((title, runtime)))
    return calls


def _items(name: str):
    return list(wp_theatre._parse_production((_FIXTURES / name).read_text(), _SITE))


def _parse(name: str):
    return [i for i in _items(name) if not isinstance(i, Film)]


def _film(name: str) -> Film:
    return next(i for i in _items(name) if isinstance(i, Film))


def test_production_screenings(tmdb_calls):
    screenings = _parse("production-tony.html")
    assert len(screenings) == 4
    s = screenings[0]
    assert s.title == "Tony"
    assert s.date.isoformat() == "2026-09-20"
    assert s.time.strftime("%H:%M") == "17:30"
    assert s.screen == "CAPITOL 1"
    assert s.cinema_name == "Capitol"
    assert s.city == "Göteborg"
    assert s.ticket_url.startswith("https://capitolgbg.internetbokningen.com/")
    assert s.film_key == "wp_theatre:tony"


def test_film_metadata(tmdb_calls):
    film = _film("production-tony.html")
    assert film.key == "wp_theatre:tony"
    assert film.overview.startswith("En 19-årig Anthony Bourdain reser till Provincetown")
    # The body ends at the runtime line; the showtimes listing is not part of it.
    assert film.overview.endswith("TV-profilen.")
    assert film.runtime == 106
    assert film.genres == ["Drama", "Dokumentär"]
    assert film.poster_url == "https://www.capitolgbg.se/wp-content/uploads/2026/09/tony.jpg"
    assert film.url == "https://www.capitolgbg.se/produktion/tony/"


def test_series_category_is_not_a_genre(tmdb_calls):
    film = _film("production-cinemateket.html")
    assert film.genres == []
    assert film.overview == ""
    assert film.title == "Cinemateket: Blade Runner"


def test_runtime_is_passed_to_tmdb(tmdb_calls):
    _parse("production-tony.html")
    assert tmdb_calls == [("Tony", 106)]


def test_series_prefix_stripped_for_tmdb(tmdb_calls):
    screenings = _parse("production-cinemateket.html")
    assert tmdb_calls == [("Blade Runner", None)]
    # The displayed title keeps the series label.
    assert screenings[0].title == "Cinemateket: Blade Runner"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Cinemateket: Blade Runner", "Blade Runner"),
        ("Unga Cinemateket: När Marnie var där (Sv. tal)", "När Marnie var där (Sv. tal)"),
        ("Tony", "Tony"),
    ],
)
def test_lookup_title(text, expected):
    assert wp_theatre._lookup_title(text) == expected
