"""Standalone Tickster imports: mixed programmes, real event times and safe replacement."""

from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from parse import _available
from parse.parsers import tickster_se as parser
from store import Film, Screening
from store.version import Language

_FIXTURES = Path(__file__).parent / "fixtures" / "tickster_se"
_FINSPANG = (_FIXTURES / "finspang.html").read_text()
_EMMABODA = (_FIXTURES / "emmaboda.html").read_text()
_ROXY = (_FIXTURES / "roxy.html").read_text()
_SKARPNACK = (_FIXTURES / "skarpnack.html").read_text()
_URL = "https://www.tickster.com/se/sv/events/juta7n5a59zxapn/2026-11-15/bio-sjung-for-mig-arja"


def _card(url, title="Bio: Sjung för mig Arja", day="15 nov 2026"):
    return (
        f'<div class="c-card"><a class="c-card__body" href="{url}">'
        f'<div class="c-card__label">{day}, Kulturhuset Finspång, Finspång</div>'
        f'<h2 class="c-card__title">{title}</h2></a></div>'
    )


def _setup(monkeypatch, programme, *, pages=None, site=None):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 13, tzinfo=tz)

    site = site or parser._SITES[0]
    responses = {parser._BASE + site.organiser: programme, _URL: _FINSPANG, **(pages or {})}

    def get(url, timeout):
        if url not in responses:
            raise requests.ConnectionError(url)
        return SimpleNamespace(text=responses[url], raise_for_status=lambda: None)

    monkeypatch.setattr(parser, "datetime", Clock)
    monkeypatch.setattr(parser, "_SITES", (site,))
    monkeypatch.setattr(parser._http, "session", lambda: SimpleNamespace(get=get))
    monkeypatch.setattr(parser, "_tmdb", lambda title: None)


def test_mixed_programme_follows_pages_and_uses_start_not_doors(monkeypatch):
    following = parser._BASE + parser._SITES[0].organiser + "?skip=24&take=24"
    programme = (
        _card("gift", "Presentkort Bio")
        + _card("template", day="15 nov 2045")
        + _card("past", day="12 nov 2026")
        + _card("concert", "Konsert: Linnea Henriksson")
        + _card(_URL)
        + f'<a class="c-pager__page" href="{following}">Nästa</a>'
    )
    second = _URL + "?second"
    _setup(
        monkeypatch,
        programme,
        pages={
            "https://www.tickster.com/concert": '<a rel="tag">Musik</a>',
            following: _card(_URL) + _card(second),
            second: _FINSPANG.replace("2026-11-15T19:00:00", "2026-11-15T21:00:00").replace(_URL, second),
        },
    )
    items = list(parser.parse())
    assert "tickster_se" in _available()
    screenings = [i for i in items if isinstance(i, Screening)]
    assert [(s.title, s.date, s.time, s.screen) for s in screenings] == [
        ("Sjung för mig Arja", date(2026, 11, 15), time(19), "Stora Salongen"),
        ("Sjung för mig Arja", date(2026, 11, 15), time(21), "Stora Salongen"),
    ]
    assert screenings[0].ticket_url == _URL
    assert screenings[0].cinema_name == "Kulturhuset Finspång"
    assert screenings[0].city == "Finspång"
    assert screenings[0].raw_attributes == ("Bio",)
    films = [i for i in items if isinstance(i, Film)]
    assert len(films) == 1
    assert films[0].overview
    assert films[0].runtime is None  # endDate describes the event slot, not a film runtime.
    assert films[0].poster_url == ""  # The 960x540 banner is not a poster.


@pytest.mark.parametrize(
    ("site_index", "page", "title", "screen", "language", "subtitles"),
    [
        (1, _EMMABODA, "The Hunger Games: Sunrise on the reaping", "", {Language.ENGLISH}, None),
        (8, _ROXY, "André Rieu's Christmas concert: Let it snow!", "Salong 2", set(), None),
        (11, _SKARPNACK, "Kärlek över Tanger", "A-salen", {Language.SPANISH}, {Language.SWEDISH}),
    ],
)
def test_event_versions_truncated_tags_and_cinema_broadcasts(
    monkeypatch, site_index, page, title, screen, language, subtitles
):
    site = parser._SITES[site_index]
    _setup(monkeypatch, _card(_URL), pages={_URL: page}, site=site)
    items = list(parser.parse())
    screening = next(i for i in items if isinstance(i, Screening))
    film = next(i for i in items if isinstance(i, Film))
    assert (screening.title, screening.screen) == (title, screen)
    assert screening.version.audio.languages == language
    assert screening.version.subtitles.languages == subtitles
    assert "Framträdanden av" not in film.overview


@pytest.mark.parametrize(
    "page",
    [
        _FINSPANG.replace(">Finspång<", ">Norrköping<"),
        _FINSPANG.replace("Kulturhuset Finspång, Stora Salongen", "Annan biograf"),
        _FINSPANG.replace("Bio: Sjung för mig Arja", "Presentkort Bio"),
        _FINSPANG + '<meta itemprop="eventStatus" content="https://schema.org/EventCancelled">',
    ],
)
def test_does_not_import_other_venues_gift_cards_or_cancellations(monkeypatch, page):
    _setup(monkeypatch, _card(_URL), pages={_URL: page})
    assert not any(isinstance(item, Screening) for item in parser.parse())


@pytest.mark.parametrize("failure", ["event", "pagination", "unreadable"])
def test_incomplete_programmes_fail_instead_of_replacing_stored_screenings(monkeypatch, failure):
    programme = _card(_URL)
    pages = {}
    if failure == "event":
        programme += _card("unreachable")
    elif failure == "pagination":
        programme += '<a class="c-pager__page" href="unreachable">Nästa</a>'
    else:
        pages[_URL] = _FINSPANG.replace('itemprop="startDate"', 'itemprop="missing"')
    _setup(monkeypatch, programme, pages=pages)
    with pytest.raises((requests.ConnectionError, ValueError)):
        list(parser.parse())
