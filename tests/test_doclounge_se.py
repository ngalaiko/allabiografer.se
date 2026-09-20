"""doclounge.se event extraction."""

from datetime import date, time
from pathlib import Path

from parse.parsers import doclounge_se
from parse.parsers.doclounge_se import _events, _film_details, _film_slugs
from store import Film, Screening, film_key

_HTML = (Path(__file__).parent / "fixtures" / "doclounge_se" / "events-screenings.html").read_text()


def _by_date(html: str) -> dict[date, tuple]:
    return {e[1]: e for e in _events(html)}


def test_upcoming_events_without_a_city_term_fall_back_to_the_venue():
    events = _by_date(_HTML)

    # Both carry "cities": {"nodes": []}; the city comes from the venue seen elsewhere.
    assert events[date(2026, 9, 28)][4:6] == ("Moriska Paviljongen", "Malmö")
    assert events[date(2026, 10, 1)][4:6] == ("Skeppet Gbg", "Göteborg")


def test_events_keep_title_time_and_ticket_url():
    title, day, clock, ticket_url, cinema, city, address = _by_date(_HTML)[date(2026, 10, 1)]

    assert title == "Cambodian Beer Dreams"
    assert day == date(2026, 10, 1)
    assert clock == time(18, 0)
    assert ticket_url.startswith("https://billetto.se/")
    assert (cinema, city, address) == ("Skeppet Gbg", "Göteborg", "Amerikagatan 2")


def test_one_venue_spelled_two_ways_collapses_to_one_name():
    events = _by_date(_HTML)

    # The site writes "Skeppet Gbg" on upcoming events and "Skeppet GBG" on older ones.
    assert events[date(2026, 10, 1)][4] == events[date(2025, 12, 3)][4] == "Skeppet Gbg"


def test_a_street_only_address_is_not_used_as_a_cinema_name():
    # "Karlsgatan 7, 252 24 Helsingborg" names no venue.
    assert _by_date(_HTML)[date(2025, 4, 4)][4] == "Doc Lounge Helsingborg"


_FILM_HTML = (Path(__file__).parent / "fixtures" / "doclounge_se" / "film.html").read_text()


def test_each_event_title_maps_to_its_film_page_slug():
    assert _film_slugs(_HTML) == {
        "Sofijah": "sofijah",
        "Cambodian Beer Dreams": "camdodian-beer-dreams",
        "Queer as punk": "queer-as-punk",
        "The Dating Game": "the-dating-game",
        "Jag ska bara gråta lite först": "jag-ska-bara-grata-lite-forst",
    }


def test_film_details_read_poster_synopsis_runtime_original_title_and_year():
    details = _film_details(_FILM_HTML)

    assert details["poster_url"] == (
        "https://www.doclounge.se/_next/image?url=https%3A%2F%2Fmedia.doclounge.se%2Fwp-content"
        "%2Fuploads%2F2026%2F05%2FDIGITALPOSTER_FBPM_-V5_FINAL__GUL-scaled.jpg&w=640&q=75"
    )
    assert details["overview"].startswith("Douglas “Dogge Doggelito” Léon")
    # The fact list bulleted with "➤" ends the synopsis.
    assert "Speltid" not in details["overview"]
    assert details["runtime"] == 82
    assert details["genres"] == ["Dokumentär"]
    assert details["title_original"] == "Första blatten på månen"
    assert details["release_date"] == "2026"


def test_parse_yields_one_film_per_title_and_keys_every_screening(monkeypatch):
    monkeypatch.setattr(
        doclounge_se, "_fetch", lambda session, url: _HTML if url.endswith("events-screenings") else _FILM_HTML
    )
    monkeypatch.setattr(doclounge_se._films, "register", lambda film, session=None: film)
    monkeypatch.setattr(doclounge_se, "_tmdb", lambda title: None)

    items = list(doclounge_se.parse())
    films = [i for i in items if isinstance(i, Film)]
    screenings = [i for i in items if isinstance(i, Screening)]

    assert [f.key for f in films] == [film_key("doclounge_se", f.title) for f in films]
    assert {s.film_key for s in screenings} == {f.key for f in films}
    assert all(s.film_key for s in screenings)
