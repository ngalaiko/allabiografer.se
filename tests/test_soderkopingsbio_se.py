"""soderkopingsbio.se schedule API extraction and Tickster ticket lookup."""

import json
from datetime import date, time
from pathlib import Path
from types import SimpleNamespace

import requests

from parse.parsers import _biosverige_api, soderkopingsbio_se
from parse.parsers._biosverige_api import film_details as _film_details
from parse.parsers._biosverige_api import parse_title as _parse_title
from parse.parsers._biosverige_api import showtimes as _showtimes
from store import Film, Language, Screening, film_key

_FIXTURES = Path(__file__).parent / "fixtures" / "soderkopingsbio_se"
_SCHEDULE = json.loads((_FIXTURES / "eventschedules.json").read_text())
_MOVIE = json.loads((_FIXTURES / "movie.json").read_text())

_TICKSTER = Path(__file__).parent / "fixtures" / "tickster"
_ORGANISER = (_TICKSTER / "organiser.html").read_text()
_MATINEE = (_TICKSTER / "event_matinee.html").read_text()
_EVENING = (_TICKSTER / "event_evening.html").read_text()

_API = soderkopingsbio_se._SITE + "/api/eventschedules"
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


def _parse(monkeypatch, pages: dict[str, object], tmdb=lambda title, runtime=None: None) -> list:
    monkeypatch.setattr(soderkopingsbio_se._http, "session", lambda *a: _Session(pages))
    monkeypatch.setattr(soderkopingsbio_se._films, "register", lambda film, session=None: film)
    monkeypatch.setattr(_biosverige_api, "_tmdb", tmdb)
    return list(soderkopingsbio_se.parse())


def test_parse_yields_one_film_per_title_and_keys_every_screening(monkeypatch):
    items = _parse(monkeypatch, {_API: _SCHEDULE})
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
            _API: _SCHEDULE,
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
    items = _parse(monkeypatch, {_API: _SCHEDULE})

    assert {i.ticket_url for i in items if isinstance(i, Screening)} == {"https://secure.tickster.com/d8fnyrrcl72fv8p"}


def test_parse_title_labels_subtitles():
    assert _parse_title("Tony (Sv.Txt) (Eng.Tal)") == ("Tony", "Engelskt tal", "Svensk text")


def test_parse_title_reads_any_known_language_code():
    assert _parse_title("Köln 75 (Sv.Txt) (Ty.Tal)") == ("Köln 75", "Tyskt tal", "Svensk text")


def test_parse_title_drops_unknown_language_codes():
    assert _parse_title("Film (Xq.Tal)") == ("Film", "", "")


def test_parse_keeps_tickster_programme_tags_as_raw_attributes(monkeypatch):
    items = _parse(
        monkeypatch,
        {
            _API: _SCHEDULE,
            soderkopingsbio_se._TICKSTER: _ORGANISER,
            _MATINEE_URL: _MATINEE,
            _EVENING_URL: _EVENING,
        },
    )
    screenings = [i for i in items if isinstance(i, Screening)]

    assert [s.raw_attributes for s in screenings] == [(), ("Dagbio",), ("Dagbio",), ()]


def _card(path: str, title: str, label: str) -> str:
    return (
        f'<div class="c-card"><a href="/se/sv/events/{path}" class="c-card__body">'
        f'<h2 class="c-card__title">{title}</h2></a>'
        f'<span class="c-card__label">{label}, Söderköpings Bio</span></div>'
    )


def test_tickster_version_overrides_the_schedule_tags(monkeypatch):
    schedule = [
        {"eventName": "Bortglömda ön (Sv.Txt) (Sv. Tal)", "startDate": "2026-10-18T15:00:00", "venueName": "Sal 1"},
        {"eventName": "Digger (Sv.Txt) (Eng.Tal)", "startDate": "2026-10-18T18:30:00", "venueName": "Sal 1"},
    ]
    organiser = _card("a/2026-10-18/bortglomda-on-sv-tal", "Bortglömda ön (Sv. tal)", "18 okt 2026") + _card(
        "b/2026-10-18/digger-sv-txt", "Digger (Sv. txt)", "18 okt 2026"
    )
    items = _parse(monkeypatch, {_API: schedule, soderkopingsbio_se._TICKSTER: organiser})
    island, digger = [i for i in items if isinstance(i, Screening)]

    assert island.version.audio.languages == {Language.SWEDISH}
    assert island.version.subtitles.languages == frozenset()
    assert digger.version.audio.languages == {Language.ENGLISH}
    assert digger.version.subtitles.languages == {Language.SWEDISH}


def test_parse_looks_up_tmdb_with_the_api_runtime_first(monkeypatch):
    def tmdb(title, runtime=None):
        return {("Tony", 106): 7, ("Resan till Piemonte", None): 8}.get((title, runtime))

    items = _parse(monkeypatch, {_API: _SCHEDULE}, tmdb=tmdb)

    assert [s.tmdb_id for s in items if isinstance(s, Screening)] == [None, 8, 7, 8]


def test_parse_skips_deleted_showings(monkeypatch):
    schedule = [{**_SCHEDULE[0], "deleted": True}, *_SCHEDULE[1:]]
    items = _parse(monkeypatch, {_API: schedule})

    assert len([i for i in items if isinstance(i, Screening)]) == 3


def test_parse_survives_a_non_list_schedule(monkeypatch):
    items = _parse(monkeypatch, {_API: {"message": "error"}})

    assert [i.name for i in items] == ["Söderköpings Bio"]


def test_parse_survives_an_unreachable_schedule(monkeypatch):
    items = _parse(monkeypatch, {})

    assert [i.name for i in items] == ["Söderköpings Bio"]
