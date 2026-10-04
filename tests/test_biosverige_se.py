"""BioSverige (Cinecore) schedule API extraction across cinema sites."""

import json
from datetime import date, time
from pathlib import Path
from types import SimpleNamespace

import requests

from parse.parsers import biosverige_se
from parse.parsers.biosverige_se import _film_details, _parse_title, _showtimes
from store import Film, Screening, Venue, film_key

_FIXTURES = Path(__file__).parent / "fixtures" / "biosverige_se"
_SCHEDULE = json.loads((_FIXTURES / "eventschedules.json").read_text())


def test_showtimes_read_schedule_rows_with_screen_and_audio_tags():
    assert [s[:6] for s in _showtimes(_SCHEDULE)] == [
        ("Bortglömda ön", date(2026, 10, 4), time(15, 0), "Casablanca", "Svenskt tal", "Svensk text"),
        ("Resan till Piemonte", date(2026, 10, 4), time(18, 30), "Casablanca", "Svenskt tal", "Svensk text"),
        ("Resan till Piemonte", date(2026, 10, 6), time(14, 0), "Casablanca", "Svenskt tal", "Svensk text"),
        ("Kärlek över Tanger", date(2026, 10, 13), time(14, 0), "Casablanca", "", "Svensk text"),
    ]


def test_showtimes_skip_rows_without_start_or_title():
    rows = [{"eventName": "Film", "startDate": ""}, {"eventName": "", "startDate": "2026-10-04T15:00:00"}]

    assert list(_showtimes(rows)) == []


def test_film_details_read_the_movie_record():
    details = _film_details(_SCHEDULE[3]["movie"])

    assert details["poster_url"] == (
        "https://cdn.incode.se/content/E4046CAD-672D-4E04-829C-DFB7C472E7A7.jpg?resize=600x900"
    )
    assert details["overview"].startswith("En sensuell och hjärtevärmande feelgood")
    assert details["runtime"] == 116
    assert details["age_rating"] == "Barntillåten"
    assert details["title_original"] == "Calle Malaga"
    assert details["release_date"] == "2026-10-09"
    assert details["genres"] == []


def test_parse_title_reads_spaced_and_unspaced_tags():
    assert _parse_title("Bortglömda ön (Sv.Txt) (Sv. Tal)") == ("Bortglömda ön", "Svenskt tal", "Svensk text")
    assert _parse_title("Digger (Sv.Txt) (Eng.Tal)") == ("Digger", "Engelskt tal", "Svensk text")


def test_parse_title_drops_unknown_language_codes():
    assert _parse_title("Film (Xq.Tal)") == ("Film", "", "")


def test_sites_exclude_cinemas_other_parsers_cover():
    hosts = {site.url for site in biosverige_se._SITES}

    assert not any("soderkoping" in h for h in hosts)


class _Session:
    def __init__(self, pages: dict[str, object]):
        self.pages = pages

    def get(self, url, params=None, timeout=None):
        if url not in self.pages:
            raise requests.ConnectionError(url)
        body = self.pages[url]
        return SimpleNamespace(json=lambda: body, raise_for_status=lambda: None)


_KARLSBORG, _FILIPSTAD = (
    next(s for s in biosverige_se._SITES if s.city == city) for city in ("Karlsborg", "Filipstad")
)


def _parse(monkeypatch, pages: dict[str, object]) -> list:
    monkeypatch.setattr(biosverige_se._http, "session", lambda *a: _Session(pages))
    monkeypatch.setattr(biosverige_se._films, "register", lambda film, session=None: film)
    monkeypatch.setattr(biosverige_se, "_tmdb", lambda title: None)
    return list(biosverige_se.parse())


def test_parse_yields_venues_films_and_screenings(monkeypatch):
    items = _parse(monkeypatch, {_KARLSBORG.url + "/api/eventschedules": _SCHEDULE})
    venues = [i for i in items if isinstance(i, Venue)]
    films = [i for i in items if isinstance(i, Film)]
    screenings = [i for i in items if isinstance(i, Screening)]

    assert len(venues) == len(biosverige_se._SITES)
    assert [f.title for f in films] == ["Bortglömda ön", "Resan till Piemonte", "Kärlek över Tanger"]
    assert [f.key for f in films] == [film_key("biosverige_se", f.title) for f in films]
    assert films[0].url == "https://casablancabio.se/filmer/bortglomda-on-(svtxt)-(sv-tal)_1"
    assert len(screenings) == 4
    assert {s.film_key for s in screenings} == {f.key for f in films}
    assert {(s.cinema_name, s.city) for s in screenings} == {(_KARLSBORG.name, "Karlsborg")}
    assert {s.ticket_url for s in screenings} == {_KARLSBORG.tickets}


def test_parse_shares_films_across_sites_and_survives_a_failing_site(monkeypatch):
    items = _parse(
        monkeypatch,
        {_KARLSBORG.url + "/api/eventschedules": _SCHEDULE, _FILIPSTAD.url + "/api/eventschedules": _SCHEDULE[:1]},
    )
    films = [i for i in items if isinstance(i, Film)]
    screenings = [i for i in items if isinstance(i, Screening)]

    assert [f.title for f in films].count("Bortglömda ön") == 1
    assert {s.city for s in screenings} == {"Karlsborg", "Filipstad"}
    assert len(screenings) == 5
