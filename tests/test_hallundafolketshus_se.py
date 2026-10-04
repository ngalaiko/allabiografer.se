"""hallundafolketshus.se CaféBio event extraction."""

from datetime import date, time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from parse.parsers import _films, hallundafolketshus_se
from parse.parsers.hallundafolketshus_se import _SOURCE, _details, _events
from store import Film, Language, Screening

pytestmark = pytest.mark.usefixtures("parser_clock")

_FIXTURES = Path(__file__).parent / "fixtures" / "hallundafolketshus_se"
_HTML = (_FIXTURES / "index.html").read_text()
_EVENT = (_FIXTURES / "event.html").read_text()
_UNRATED = (_FIXTURES / "event_unrated.html").read_text()
_OPERA = (_FIXTURES / "event_opera.html").read_text()
_FILM = (_FIXTURES / "event_film.html").read_text()
_TICKSTER_OPERA = (_FIXTURES / "tickster_opera.html").read_text()
_TICKSTER_FILM = (_FIXTURES / "tickster_film.html").read_text()

_SITE = "https://www.hallundafolketshus.se/events/"
_TICKSTER = "https://www.tickster.com/se/sv/events/"


def test_events_link_to_their_own_event_page():
    events = list(_events(_HTML))

    assert events == [
        (
            "Autofiktion",
            date(2026, 9, 22),
            time(13, 0),
            "https://www.hallundafolketshus.se/events/autofiktion",
        ),
        (
            "Resan till Piemonte",
            date(2026, 9, 29),
            time(13, 0),
            "https://www.hallundafolketshus.se/events/resan-till-piemonte",
        ),
        (
            "Första blatten på månen",
            date(2026, 10, 5),
            time(19, 0),
            "https://www.hallundafolketshus.se/events/forsta-blatten-pa-manen",
        ),
        (
            "Macbeth",
            date(2026, 10, 17),
            time(19, 0),
            "https://www.hallundafolketshus.se/events/macbeth-2",
        ),
    ]


def test_event_page_carries_poster_genres_runtime_and_synopsis():
    details = _details(_EVENT)

    assert details["poster_url"] == (
        "https://www-static.hallundafolketshus.se/wp-content/uploads/2026/08/"
        "2026-09-22-Autofiktion_SE_1080x1920_Reviews-scaled.jpg"
    )
    assert details["genres"] == ["Drama"]
    assert details["runtime"] == 111
    assert details["overview"].startswith("Oscarsbelönade Pedro Almodóvar")


def test_details_make_a_film_the_screenings_key_matches():
    film = _films.make(
        _SOURCE, "Autofiktion", url="https://www.hallundafolketshus.se/events/autofiktion", **_details(_EVENT)
    )

    assert film.key == "hallundafolketshus_se:autofiktion"
    assert film.runtime == 111
    assert film.poster_url.endswith(".jpg")
    assert film.url == "https://www.hallundafolketshus.se/events/autofiktion"


def test_unset_age_rating_is_not_mistaken_for_metadata():
    details = _details(_UNRATED)

    assert details["age_rating"] == ""
    assert details["runtime"] is None
    assert details["genres"] == ["Drama", "Komedi", "Romantik"]
    assert details["overview"].startswith("Fyra vänner")


def test_opera_page_carries_runtime_and_synopsis():
    details = _details(_OPERA)

    assert details["runtime"] == 209
    assert details["poster_url"].endswith("/2026/06/Macbeth_Affisch_A3_utan-dike_webb.jpg")
    assert details["overview"].startswith("Lise Davidsen och Quinn Kelsey.")


def test_film_page_carries_labelled_runtime_and_genres():
    details = _details(_FILM)

    assert details["runtime"] == 82
    assert details["genres"] == ["Dokumentär", "musik"]
    assert details["overview"].startswith("Dogge Doggelito var rösten")


class _Session:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def get(self, url, timeout=None):
        if url not in self.pages:
            raise requests.ConnectionError(url)
        return SimpleNamespace(text=self.pages[url], raise_for_status=lambda: None)


def _parse(monkeypatch, pages: dict[str, str]) -> list:
    monkeypatch.setattr(hallundafolketshus_se, "_SESSION", _Session(pages))
    monkeypatch.setattr(hallundafolketshus_se._films, "register", lambda film, session=None: film)
    monkeypatch.setattr(hallundafolketshus_se, "_tmdb", lambda title: None)
    return list(hallundafolketshus_se.parse())


_PAGES = {
    hallundafolketshus_se._URL: _HTML,
    _SITE + "autofiktion": _EVENT,
    _SITE + "resan-till-piemonte": _UNRATED,
    _SITE + "forsta-blatten-pa-manen": _FILM,
    _SITE + "macbeth-2": _OPERA,
    _TICKSTER + "a599gz8rg90w18g": _TICKSTER_FILM,
    _TICKSTER + "370ycv26ht5bcbb": _TICKSTER_OPERA,
}


def test_screenings_take_ticket_version_and_screen_from_tickster(monkeypatch):
    screenings = {s.title: s for s in _parse(monkeypatch, _PAGES) if isinstance(s, Screening)}

    film = screenings["Första blatten på månen"]
    assert film.ticket_url == _TICKSTER + "a599gz8rg90w18g/2026-10-05/forsta-blatten-pa-manen-tal-svenska-text-ej"
    assert film.screen == "Brage"
    assert film.version.audio.languages == {Language.SWEDISH}
    assert film.version.subtitles.languages == frozenset()


def test_opera_screening_carries_the_stated_version(monkeypatch):
    items = _parse(monkeypatch, _PAGES)
    opera = next(s for s in items if isinstance(s, Screening) and s.title == "Macbeth")
    film = next(f for f in items if isinstance(f, Film) and f.title == "Macbeth")

    assert opera.ticket_url == _TICKSTER + "370ycv26ht5bcbb/2026-10-17/macbeth-live-pa-bio-fran-metropolitan"
    assert opera.screen == "Brage"
    assert opera.version.audio.languages == {Language.ITALIAN}
    assert opera.version.subtitles.languages == {Language.SWEDISH}
    assert film.runtime == 209


def test_tickster_failure_keeps_the_site_ticket_link(monkeypatch):
    screenings = {s.title: s for s in _parse(monkeypatch, _PAGES) if isinstance(s, Screening)}

    assert screenings["Autofiktion"].ticket_url == _TICKSTER + "x2gxuyawxe3285x"
    assert screenings["Autofiktion"].screen == ""
