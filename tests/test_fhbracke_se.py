"""fhbracke.se programme and film page extraction."""

from datetime import date, time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from parse.parsers import _films, fhbracke_se
from parse.parsers.fhbracke_se import _SOURCE, _details, _listings
from store import Film, Language, Screening, film_key

pytestmark = pytest.mark.usefixtures("parser_clock")

_FIXTURES = Path(__file__).parent / "fixtures" / "fhbracke_se"
_BIO = (_FIXTURES / "bio.html").read_text()
_FILM = (_FIXTURES / "film.html").read_text()
_BIO_TICKSTER = (_FIXTURES / "bio_tickster.html").read_text()
_TICKSTER = (_FIXTURES / "tickster.html").read_text()

_OCTOBER = pytest.mark.parametrize("parser_clock", ["2026-10-04T12:00:00+02:00"], indirect=True)
_EVENTS = "https://www.tickster.com/se/sv/events/"


def test_programme_yields_showtimes_with_posters():
    shows = list(_listings(_BIO))

    assert [s["title"] for s in shows] == ["The Dog Stars", "De Gaulle: Motståndets pris"]
    assert shows[0]["date"] == date(2026, 9, 20)
    assert shows[0]["time"] == time(19, 0)
    assert shows[0]["url"] == "https://fhbracke.se/film/the-dog-stars/"
    assert shows[0]["poster_url"].endswith("GATOR_TEASER2_POSTER_SWEDEN_1440x2057_-717x1024.jpg")


def test_relative_film_links_become_absolute():
    shows = list(_listings(_BIO))

    assert shows[1]["url"] == "https://fhbracke.se/film/de-gaulle-motstandets-pris/"


def test_site_chrome_is_not_taken_for_a_poster():
    assert all("BrackeFH" not in s["poster_url"] for s in _listings(_BIO))


def test_film_page_carries_synopsis_runtime_and_age_rating():
    details = _details(_FILM)

    assert details["runtime"] == 118
    assert details["age_rating"] == "Fr.15 år"
    assert details["overview"].startswith("Från Ridley Scott")
    assert "Vi är ett gäng ungdomar" not in details["overview"]


def test_listing_and_details_combine_into_a_film():
    show = next(iter(_listings(_BIO)))
    film = _films.make(_SOURCE, show["title"], url=show["url"], poster_url=show["poster_url"], **_details(_FILM))

    assert film.key == "fhbracke_se:the dog stars"
    assert film.runtime == 118
    assert film.age_rating == "Från 15 år"
    assert film.poster_url == show["poster_url"]
    assert film.url == "https://fhbracke.se/film/the-dog-stars/"


@_OCTOBER
def test_poster_is_the_widest_srcset_candidate():
    shows = list(_listings(_BIO_TICKSTER))

    assert shows[0]["poster_url"] == (
        "https://usercontent.one/wp/fhbracke.se/wp-content/uploads/2026/09/SE_DIGGER_EM_VERT_CAST_1080x1920_INTL.jpg"
    )


class _Session:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def get(self, url, timeout=None):
        if url not in self.pages:
            raise requests.ConnectionError(url)
        return SimpleNamespace(text=self.pages[url], raise_for_status=lambda: None)


def _screenings(monkeypatch, pages: dict[str, str]) -> list[Screening]:
    monkeypatch.setattr(fhbracke_se, "_SESSION", _Session(pages))
    monkeypatch.setattr(fhbracke_se._films, "register", lambda film, session=None: film)
    monkeypatch.setattr(fhbracke_se, "_tmdb", lambda title: None)
    return [i for i in fhbracke_se.parse() if isinstance(i, Screening)]


@_OCTOBER
def test_screenings_link_their_tickster_event_and_carry_its_version(monkeypatch):
    screenings = _screenings(monkeypatch, {fhbracke_se._URL: _BIO_TICKSTER, fhbracke_se._TICKSTER: _TICKSTER})

    assert [s.ticket_url for s in screenings] == [
        _EVENTS + "3eavxf9jc033ngl/2026-10-04/digger-tal-engelska-text-svenska",
        _EVENTS + "1ec95mjphjjmenl/2026-10-11/resan-till-piemonte-tal-svenska-text-svenska",
        _EVENTS + "meyc9f2av5px8jb/2026-10-19/resan-till-piemonte-tal-svenska-text-svenska",
    ]
    assert screenings[0].version.audio.languages == {Language.ENGLISH}
    assert screenings[0].version.subtitles.languages == {Language.SWEDISH}
    assert screenings[1].version.audio.languages == {Language.SWEDISH}


@_OCTOBER
def test_tickster_failure_keeps_the_film_page_link(monkeypatch):
    screenings = _screenings(monkeypatch, {fhbracke_se._URL: _BIO_TICKSTER})

    assert [s.ticket_url for s in screenings] == [
        "https://fhbracke.se/film/digger/",
        "https://fhbracke.se/film/resan-till-piemonte/",
        "https://fhbracke.se/film/resan-till-piemonte-2/",
    ]


def _slide(title: str, when: str, href: str) -> str:
    return (
        '<div class="swiper-slide"><div class="elementor-widget-wrap">'
        f'<h2 class="elementor-heading-title">{title}</h2>'
        f'<div class="elementor-widget-text-editor">{when}</div>'
        f'<a class="elementor-button" href="{href}"><span>Läs mer &gt;&gt;</span></a></div></div>'
    )


@_OCTOBER
def test_programme_keeps_same_day_showings():
    html = _slide("Digger", "söndag 4 oktober 15:00", "/film/digger/") + _slide(
        "Digger", "söndag 4 oktober 19:00", "/film/digger-2/"
    )

    assert [(s["date"], s["time"]) for s in _listings(html)] == [
        (date(2026, 10, 4), time(15, 0)),
        (date(2026, 10, 4), time(19, 0)),
    ]


def _editor(body: str) -> str:
    return (
        '<section class="elementor-top-section"><div class="elementor-widget-text-editor">'
        f"{body}</div><span class='elementor-icon-list-text'>Åldersgräns: 11 år</span></section>"
    )


def test_overview_separates_paragraphs_with_one_blank_line():
    plain = _details(_editor("Första stycket\r\n \r\nandra  stycket.\r\n\r\nTredje<br>raden."))
    marked = _details(_editor("<p>Första stycket</p>\n<p>andra\nstycket.</p>"))

    assert plain["overview"] == "Första stycket\n\nandra stycket.\n\nTredje raden."
    assert marked["overview"] == "Första stycket\n\nandra stycket."


_SITE = "https://fhbracke.se/"
_OPERA_PAGES = {
    fhbracke_se._URL: _BIO_TICKSTER,
    fhbracke_se._TICKSTER: (_FIXTURES / "tickster_opera.html").read_text(),
    fhbracke_se._EVENTS: (_FIXTURES / "events.html").read_text(),
    _SITE + "otello/": (_FIXTURES / "event_otello.html").read_text(),
    _SITE + "simson-och-delila-2/": (_FIXTURES / "event_simson.html").read_text(),
    _SITE + "tosca-favorit-i-repris/": (_FIXTURES / "event_tosca.html").read_text(),
}


def _items(monkeypatch, pages: dict[str, str]) -> list:
    monkeypatch.setattr(fhbracke_se, "_SESSION", _Session(pages))
    monkeypatch.setattr(fhbracke_se._films, "register", lambda film, session=None: film)
    monkeypatch.setattr(fhbracke_se, "_tmdb", lambda title: None)
    return list(fhbracke_se.parse())


@_OCTOBER
def test_tickster_opera_broadcasts_missing_from_the_programme_become_screenings(monkeypatch):
    items = _items(monkeypatch, _OPERA_PAGES)
    screenings = [i for i in items if isinstance(i, Screening)]
    films = {f.title: f for f in items if isinstance(f, Film)}

    assert [(s.title, s.date, s.time, s.ticket_url, s.raw_attributes) for s in screenings[3:]] == [
        (
            "Simson och Delila",
            date(2026, 12, 5),
            time(18, 0),
            _EVENTS + "5l38n6jca26jzrr/2026-12-05/simson-och-delila",
            (),
        ),
        (
            "Tosca",
            date(2027, 2, 20),
            time(19, 0),
            _EVENTS + "ljagpjxfyteb615/2027-02-20/tosca-favorit-i-repris",
            ("Favorit i repris",),
        ),
        ("Otello", date(2027, 4, 24), time(19, 0), _EVENTS + "9kxwwpjccntxyc3/2027-04-24/otello", ()),
    ]
    otello = films["Otello"]
    assert otello.key == film_key(_SOURCE, "Otello")
    assert otello.url == _SITE + "otello/"
    assert otello.poster_url.endswith("/2026/09/Otello-768x525.jpg")
    assert otello.overview.startswith("En av dagens ledande dramatiska tenorer, Brian Jagde, tar sig an")
    assert "\n\nVerdis Otello hade premiär" in otello.overview
    assert "Köp biljetter" not in otello.overview
    assert "24 april 2027" not in otello.overview


@_OCTOBER
def test_event_pages_that_are_not_broadcasts_are_skipped(monkeypatch):
    pages = _OPERA_PAGES | {_SITE + "otello/": (_FIXTURES / "event_standup.html").read_text()}
    titles = {i.title for i in _items(monkeypatch, pages) if isinstance(i, Screening)}

    assert "Otello" not in titles
    assert "Simson och Delila" in titles
