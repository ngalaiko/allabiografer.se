"""soderkopingsbio.se schedule API extraction and Tickster ticket lookup."""

import json
from datetime import date, time
from pathlib import Path
from types import SimpleNamespace

import requests

from parse.parsers import soderkopingsbio_se
from parse.parsers.soderkopingsbio_se import _film_details, _showtimes
from store import Film, Screening, film_key

_FIXTURES = Path(__file__).parent / "fixtures" / "soderkopingsbio_se"
_SCHEDULE = json.loads((_FIXTURES / "eventschedules.json").read_text())
_MOVIE = json.loads((_FIXTURES / "movie.json").read_text())

_TICKSTER = Path(__file__).parent / "fixtures" / "tickster"
_ORGANISER = (_TICKSTER / "organiser.html").read_text()
_MATINEE = (_TICKSTER / "event_matinee.html").read_text()
_EVENING = (_TICKSTER / "event_evening.html").read_text()

_EVENTS = "https://www.tickster.com/se/sv/events/"
_MATINEE_URL = _EVENTS + "c07puyr3fdybd2e/2026-10-07/resan-till-piemonte-dagbio-sv-txt"
_EVENING_URL = _EVENTS + "mynrz5ej8n8gpee/2026-10-07/resan-till-piemonte-sv-txt"


def test_showtimes_read_schedule_rows_with_screen_and_audio_tags():
    assert [s[:6] for s in _showtimes(_SCHEDULE)] == [
        ("Avengers: Endgame Encore", date(2026, 10, 4), time(14, 0), "Sal 1", "Engelskt tal", "Svensk text"),
        ("Resan till Piemonte", date(2026, 10, 7), time(13, 0), "Sal 1", "Svenskt tal", "Svensk text"),
        ("Tony", date(2026, 10, 7), time(15, 30), "Sal 1", "Engelskt tal", "Svensk text"),
        ("Resan till Piemonte", date(2026, 10, 7), time(18, 30), "Sal 1", "Svenskt tal", "Svensk text"),
    ]


def test_showtimes_carry_the_movie_record():
    movie = next(iter(_showtimes(_SCHEDULE)))[6]

    assert movie["slug"] == "avengers-endgame-encore-(svtxt)-(engtal)_3"
    assert _film_details(movie)["runtime"] == 183


def test_film_details_read_the_movie_api_record():
    details = _film_details(_MOVIE)

    assert details["poster_url"] == (
        "https://cdn.incode.se/content/61BB6B68-BF8C-4771-A803-A58F5B6DDE62.jpg?resize=600x900"
    )
    assert details["overview"].startswith("En 19-årig Anthony Bourdain")
    assert details["runtime"] == 106
    assert details["age_rating"] == "11 år"
    assert details["title_original"] == "Tony"
    assert details["release_date"] == "2026-09-18"
    # The API carries a genre field, always null.
    assert details["genres"] == []


class _Session:
    def __init__(self, pages: dict[str, object]):
        self.pages = pages

    def get(self, url, params=None, timeout=None):
        if url not in self.pages:
            raise requests.ConnectionError(url)
        body = self.pages[url]
        return SimpleNamespace(
            text=body if isinstance(body, str) else "",
            json=lambda: body,
            raise_for_status=lambda: None,
        )


def _parse(monkeypatch, pages: dict[str, object]) -> list:
    monkeypatch.setattr(soderkopingsbio_se._http, "session", lambda *a: _Session(pages))
    monkeypatch.setattr(soderkopingsbio_se._films, "register", lambda film, session=None: film)
    monkeypatch.setattr(soderkopingsbio_se, "_tmdb", lambda title: None)
    return list(soderkopingsbio_se.parse())


def test_parse_yields_one_film_per_title_and_keys_every_screening(monkeypatch):
    items = _parse(monkeypatch, {soderkopingsbio_se._SCHEDULE: _SCHEDULE})
    films = [i for i in items if isinstance(i, Film)]
    screenings = [i for i in items if isinstance(i, Screening)]

    assert items[0].address == "Ringvägen 45 A"
    assert [f.key for f in films] == [film_key("soderkopingsbio_se", f.title) for f in films]
    assert [f.title for f in films] == ["Avengers: Endgame Encore", "Resan till Piemonte", "Tony"]
    assert films[0].url == "https://soderkopingsbio.se/filmer/avengers-endgame-encore-(svtxt)-(engtal)_3"
    assert films[0].runtime == 183
    assert len(screenings) == 4
    assert {s.film_key for s in screenings} == {f.key for f in films}


def test_parse_links_each_screening_to_its_tickster_event(monkeypatch):
    items = _parse(
        monkeypatch,
        {
            soderkopingsbio_se._SCHEDULE: _SCHEDULE,
            soderkopingsbio_se._TICKSTER: _ORGANISER,
            _MATINEE_URL: _MATINEE,
            _EVENING_URL: _EVENING,
        },
    )
    screenings = [i for i in items if isinstance(i, Screening)]

    assert [s.ticket_url for s in screenings] == [
        _EVENTS + "94djmvtwe7g13mp/2026-10-04/avengers-endgame-encore-sv-txt",
        _MATINEE_URL,
        _EVENTS + "dy0aclymmplt6bf/2026-10-07/tony-dagbio-sv-txt",
        _EVENING_URL,
    ]


def test_tickster_failure_falls_back_to_the_programme_link(monkeypatch):
    items = _parse(monkeypatch, {soderkopingsbio_se._SCHEDULE: _SCHEDULE})

    assert {i.ticket_url for i in items if isinstance(i, Screening)} == {"https://secure.tickster.com/d8fnyrrcl72fv8p"}


def test_parse_title_labels_subtitles():
    assert soderkopingsbio_se._parse_title("Tony (Sv.Txt) (Eng.Tal)") == ("Tony", "Engelskt tal", "Svensk text")


def test_parse_title_reads_any_known_language_code():
    assert soderkopingsbio_se._parse_title("Köln 75 (Sv.Txt) (Ty.Tal)") == ("Köln 75", "Tyskt tal", "Svensk text")


def test_parse_title_drops_unknown_language_codes():
    assert soderkopingsbio_se._parse_title("Film (Xq.Tal)") == ("Film", "", "")
