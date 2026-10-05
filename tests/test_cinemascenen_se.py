"""Cinemascenen city programmes and film metadata."""

from datetime import date, time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from parse import _available
from parse.parsers import cinemascenen_se as parser
from store import Film, Screening, Venue
from store.version import Language

_FIXTURES = Path(__file__).parent / "fixtures" / "cinemascenen_se"


def _html(name):
    return (_FIXTURES / f"{name}.html").read_text()


@pytest.mark.parametrize(
    ("slug", "city", "count"),
    [
        ("ystad", "Ystad", 12),
        ("katrineholm", "Katrineholm", 6),
        ("strangnas", "Strängnäs", 7),
        ("soderhamn", "Söderhamn", 6),
        ("hudiksvall", "Hudiksvall", 6),
    ],
)
def test_city_programmes(slug, city, count):
    rows = list(parser._showtimes(_html(slug), city))
    assert len(rows) == count
    assert {s.city for _, s in rows} == {city}
    assert len({s.date for _, s in rows}) == 2
    assert all(s.film_key == f.key for f, s in rows)
    assert all(s.cinema_name == "Cinemascenen" for _, s in rows)


def test_showtime_fields_and_metadata():
    film, screening = next(parser._showtimes(_html("ystad"), "Ystad"))
    assert film.title == "DIGGER"
    assert film.runtime == 129
    assert film.age_rating == "Från 11 år"
    assert screening.date == date(2026, 10, 7)
    assert screening.time == time(18)
    assert screening.screen == "SALONG RIO"
    assert screening.ticket_url == "https://secure.tickster.com/py11388ypp0j16z"
    assert screening.version.audio.languages == frozenset()
    assert screening.version.subtitles.languages is None


def test_swedish_audio_without_assumed_subtitles():
    film, screening = next((f, s) for f, s in parser._showtimes(_html("ystad"), "Ystad") if "BORTGL" in f.title)
    assert film.runtime == 109
    assert screening.version.audio.languages == frozenset({Language.SWEDISH})
    assert screening.version.subtitles.languages is None
    assert "Sv tal" in screening.raw_attributes[0]


def test_film_details_exclude_credits_and_trailer():
    film, _ = next((f, s) for f, s in parser._showtimes(_html("ystad"), "Ystad") if "BORTGL" in f.title)
    detailed = parser._details(_html("film"), film)
    assert detailed.overview.startswith("Jo och Raissa har varit bästa vänner")
    assert detailed.overview.endswith("för evigt.")
    assert detailed.poster_url.endswith("bortglomdaposter-717x1024.jpg")
    assert detailed.key == film.key
    assert detailed.title == "Bortglömda ön"


def test_programme_text_is_uppercased_beyond_ascii():
    rows = list(parser._showtimes(_html("hudiksvall"), "Hudiksvall"))
    assert "SALONG RÖDA KVARN" in {s.screen for _, s in rows}
    assert not any("ö" in f.title for f, _ in rows)


def test_screenings_take_film_page_title(monkeypatch):
    def get(url, timeout):
        if url == parser._URL + "ystad/":
            return SimpleNamespace(text=_html("ystad"), raise_for_status=lambda: None)
        if "bortglomda-on" in url:
            return SimpleNamespace(text=_html("film"), raise_for_status=lambda: None)
        raise requests.ConnectionError(url)

    monkeypatch.setattr(parser, "_SITES", parser._SITES[:1])
    monkeypatch.setattr(parser._http, "session", lambda: SimpleNamespace(get=get))
    monkeypatch.setattr(parser._films, "register", lambda film, **kwargs: film)
    titles = []
    monkeypatch.setattr(parser, "_tmdb", lambda title, **kwargs: titles.append(title))
    screenings = [i for i in parser.parse() if isinstance(i, Screening)]
    assert "Bortglömda ön" in {s.title for s in screenings}
    assert "Bortglömda ön" in titles
    assert "DIGGER" in {s.title for s in screenings}


def test_film_details_without_synopsis():
    film, _ = next(parser._showtimes(_html("ystad"), "Ystad"))
    detailed = parser._details(_html("film_upcoming"), film)
    assert detailed.overview == ""
    assert detailed.poster_url.endswith("dune3poster-717x1024.jpg")


@pytest.mark.parametrize(("old", "new"), [("2026-10-07", "2026-02-30"), ("18:00", "25:00")])
def test_invalid_dates_and_times_skip_affected_rows(old, new):
    rows = list(parser._showtimes(_html("ystad").replace(old, new), "Ystad"))
    assert rows
    assert not any(s.date == date(2026, 10, 7) and s.time == time(18) for _, s in rows)


def test_missing_ticket_uses_film_page():
    html = _html("ystad").replace('class="movie-row__button movie-row__button--ticket"', 'class="unavailable"')
    assert all(s.ticket_url == f.url for f, s in parser._showtimes(html, "Ystad"))


def test_missing_runtime_is_unknown():
    film, _ = next(parser._showtimes(_html("ystad").replace("11 år 2 tim 9 min", "tim min"), "Ystad"))
    assert film.runtime is None
    assert film.age_rating == ""


def test_parse_covers_all_cities_and_deduplicates_films(monkeypatch):
    calls = []

    def get(url, timeout):
        calls.append(url)
        for slug, _, _ in parser._SITES:
            if url == parser._URL + slug + "/":
                return SimpleNamespace(text=_html(slug), raise_for_status=lambda: None)
        raise requests.ConnectionError(url)

    monkeypatch.setattr(parser._http, "session", lambda: SimpleNamespace(get=get))
    monkeypatch.setattr(parser._films, "register", lambda film, **kwargs: film)
    monkeypatch.setattr(parser, "_tmdb", lambda *args, **kwargs: 123)
    items = list(parser.parse())
    films = [i for i in items if isinstance(i, Film)]
    screenings = [i for i in items if isinstance(i, Screening)]
    assert len([i for i in items if isinstance(i, Venue)]) == 5
    assert len(screenings) == 37
    assert len(films) == len({s.film_key for s in screenings})
    assert all(s.tmdb_id == 123 for s in screenings)
    assert len(calls) == 5 + len(films)
    assert "cinemascenen_se" in _available()
