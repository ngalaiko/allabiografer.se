"""Hypnos Theatre event listing extraction."""

from datetime import date, time
from pathlib import Path

import pytest

from parse.parsers import hypnostheatre_com as parser
from store.version import Language

pytestmark = [
    pytest.mark.usefixtures("parser_clock"),
    pytest.mark.parametrize("parser_clock", ["2026-10-05T12:00:00+02:00"], indirect=True),
]

_HTML = (Path(__file__).parent / "fixtures" / "hypnostheatre_com" / "index.html").read_text()


def _rows():
    return list(parser._showtimes(_HTML))


def test_skips_events_without_a_listed_time():
    titles = [f.title for f, _ in _rows()]
    assert len(titles) == 21
    assert "PORYES PRESENTS QUEERFEMINIST PORN" not in titles


def test_reads_showtime_and_credits():
    film, screening = _rows()[0]
    assert film.title == "JOHN WICK"
    assert film.key == "hypnostheatre_com:john wick"
    assert film.runtime == 101
    assert film.release_date == "2014"
    assert film.overview.startswith("DON'T SET HIM OFF.\n\nEx-hitman John Wick")
    # Listing images are landscape stills, unusable as posters.
    assert film.poster_url == ""
    assert (screening.date, screening.time) == (date(2026, 10, 3), time(17, 15))
    assert screening.cinema_name == "Hypnos Theatre"
    assert screening.city == "Malmö"
    assert screening.film_key == film.key
    assert screening.ticket_url == "https://filmimalmo.se"
    assert screening.version.audio.languages == frozenset({Language.ENGLISH})
    assert screening.version.subtitles.languages is None


def test_series_label_becomes_a_raw_attribute():
    _, screening = next((f, s) for f, s in _rows() if f.title == "THE IMAGINARIUM OF DOCTOR PARNASSUS")
    assert screening.raw_attributes == ("TERRY GILLIAM RETROSPECTIVE",)


def test_ticket_link_drops_tracking_query():
    _, screening = next((f, s) for f, s in _rows() if f.title.startswith("L.T. FISK"))
    assert screening.ticket_url == "https://nortic.se/ticket/event/85967"
    assert screening.date == date(2026, 10, 16)


def test_event_without_ticket_tag_links_the_listing():
    film, screening = next((f, s) for f, s in _rows() if f.title == "JOLLY")
    assert screening.ticket_url == "https://hypnostheatre.com/"
    assert film.runtime == 17
    assert screening.raw_attributes == ("Death Cafe Malmö",)
    assert screening.version.audio.languages == frozenset()


def _lookup_ignoring_runtime(title, runtime=None, year=None):
    return None if runtime else 1


def test_short_film_needs_runtime_match(monkeypatch):
    monkeypatch.setattr(parser, "_tmdb", _lookup_ignoring_runtime)
    film = next(f for f, _ in _rows() if f.title == "JOLLY")
    assert parser._tmdb_id(film) is None


def test_feature_falls_back_to_title_and_year(monkeypatch):
    monkeypatch.setattr(parser, "_tmdb", _lookup_ignoring_runtime)
    film = next(f for f, _ in _rows() if f.title == "THE ROCKY HORROR PICTURE SHOW")
    assert parser._tmdb_id(film) == 1
