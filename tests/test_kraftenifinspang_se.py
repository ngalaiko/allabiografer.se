"""Finspång's free calendar screenings supplement, rather than duplicate, Tickster."""

import copy
import json
from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from parse import _available
from parse.parsers import kraftenifinspang_se as parser
from store import Film, Screening, Venue

_DATA = json.loads((Path(__file__).parent / "fixtures/kraftenifinspang_se/events.json").read_text())
_FREE = _DATA["events"][0]


def _setup(monkeypatch, pages):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat("2026-11-12T23:30:00+00:00").astimezone(tz)

    def get(url, params, timeout):
        assert url == parser._URL
        assert params["start_date"] == "2026-11-13"
        if params["page"] > len(pages):
            raise requests.ConnectionError("Missing calendar page")
        return SimpleNamespace(json=lambda: pages[params["page"] - 1], raise_for_status=lambda: None)

    monkeypatch.setattr(parser, "datetime", Clock)
    monkeypatch.setattr(parser._http, "session", lambda: SimpleNamespace(get=get))
    monkeypatch.setattr(parser, "_tmdb", lambda title: None)


def test_imports_free_film_with_local_start_and_information_link(monkeypatch):
    _setup(monkeypatch, [_DATA])
    items = list(parser.parse())
    assert "kraftenifinspang_se" in _available()
    screenings = [i for i in items if isinstance(i, Screening)]
    assert len(screenings) == 1
    s = screenings[0]
    assert (s.title, s.date, s.time) == ("Tyst faller snön", date(2026, 11, 18), time(19))
    assert (s.city, s.cinema_name) == ("Finspång", "Kulturhuset Finspång")
    assert s.ticket_url == "https://kraftenifinspang.se/evenemang/bio-tyst-faller-snon-fri-entre/"
    assert s.raw_attributes == ("Fri entré",)
    assert s.version.audio.languages == frozenset()
    assert s.version.subtitles.languages is None
    film = next(i for i in items if isinstance(i, Film))
    assert film.key == s.film_key
    assert film.overview.startswith("Skuld, sorg och frigörelse")
    assert film.runtime is None  # The scheduled end is not a stated film runtime.
    assert next(i for i in items if isinstance(i, Venue)).address == "Bergslagsvägen 29"


@pytest.mark.parametrize(
    "changes",
    [
        {"cost": ""},
        {"cost": "110kr"},
        {"cost": "100 kr, gratis kaffe"},
        {"custom_fields": {"_ecp_custom_2": {"value": "Teater|Barn och Familj"}}},
        {"custom_fields": []},
        {"website": "https://www.tickster.com/se/sv/events/example"},
        {"description": '<p><a href="https://secure.tickster.com/example">Boka</a></p>'},
        {"all_day": True},
        {"utc_start_date": "2026-11-12 18:00:00"},
    ],
)
def test_rejects_unknown_or_paid_prices_nonfilms_and_tickster_overlap(monkeypatch, changes):
    event = copy.deepcopy(_FREE)
    event.update(changes)
    _setup(monkeypatch, [{"events": [event], "total_pages": 1}])
    assert list(parser.parse()) == []


def test_pagination_keeps_recurring_showings_deduplicates_and_converts_summer_time(monkeypatch):
    summer = dict(_FREE, utc_start_date="2027-06-30 23:15:00", cost="0 kr")
    _setup(
        monkeypatch,
        [
            {"events": [_FREE], "total_pages": 2},
            {"events": [_FREE, summer], "total_pages": 2},
        ],
    )
    items = list(parser.parse())
    assert [(i.date, i.time) for i in items if isinstance(i, Screening)] == [
        (date(2026, 11, 18), time(19)),
        (date(2027, 7, 1), time(1, 15)),
    ]
    assert len([i for i in items if isinstance(i, Film)]) == 1


def test_missing_later_page_aborts_instead_of_returning_a_partial_programme(monkeypatch):
    _setup(monkeypatch, [{"events": [_FREE], "total_pages": 2}])
    with pytest.raises(requests.ConnectionError):
        list(parser.parse())
