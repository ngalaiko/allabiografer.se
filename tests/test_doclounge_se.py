"""doclounge.se event extraction."""

from datetime import date, time
from pathlib import Path

from parse.parsers import doclounge_se
from parse.parsers.doclounge_se import _events, _film_details, _film_slugs
from store import Film, Screening, film_key
from store.version import Language

_FIXTURES = Path(__file__).parent / "fixtures" / "doclounge_se"
_HTML = (_FIXTURES / "events-screenings.html").read_text()


def _by_date(html: str) -> dict[date, tuple]:
    return {e[1]: e for e in _events(html)}


def test_upcoming_events_without_a_city_term_fall_back_to_the_venue():
    events = _by_date(_HTML)

    # Both carry "cities": {"nodes": []}; the city comes from the venue seen elsewhere.
    assert events[date(2026, 9, 28)][4:6] == ("Moriska Paviljongen", "Malmö")
    assert events[date(2026, 10, 1)][4:6] == ("Skeppet Gbg", "Göteborg")


def test_events_keep_title_time_and_ticket_url():
    title, day, clock, ticket_url, cinema, city, address, _ = _by_date(_HTML)[date(2026, 10, 1)]

    assert title == "Cambodian Beer Dreams"
    assert day == date(2026, 10, 1)
    assert clock == time(18, 0)
    assert ticket_url.startswith("https://billetto.se/")
    assert (cinema, city, address) == ("Skeppet Gbg", "Göteborg", "Amerikagatan 2")


def test_one_venue_spelled_two_ways_collapses_to_one_name():
    events = _by_date(_HTML)

    # The site writes "Skeppet Gbg" on upcoming events and "Skeppet GBG" on older ones.
    assert events[date(2026, 10, 1)][4] == events[date(2025, 12, 3)][4] == "Skeppet Gbg"


def test_a_street_only_address_names_the_venue_by_its_street():
    # "Karlsgatan 7, 252 24 Helsingborg" names no venue, and no named venue shares the street.
    assert _by_date(_HTML)[date(2025, 4, 4)][4:6] == ("Karlsgatan 7", "Helsingborg")


def test_a_street_only_address_takes_the_name_of_a_venue_at_that_street():
    events = _by_date(_HTML)

    # "Cafe Ray, Södra Storgatan 39A Helsingborg" and "Storgatan 39A, Helsingborg".
    assert events[date(2026, 9, 17)][4:6] == ("Cafe Ray", "Helsingborg")
    assert events[date(2026, 4, 22)][4:6] == ("Cafe Ray", "Helsingborg")
    # "Media Evolution City, Stora Varvsgatan 6a, 211 19 Malmö" and "Stora Varvsgatan 6A".
    assert events[date(2025, 2, 14)][4:6] == ("Media Evolution City", "Malmö")
    assert events[date(2026, 6, 12)][4:6] == ("Media Evolution City", "Malmö")


_FILM_HTML = (_FIXTURES / "film.html").read_text()


def test_each_event_title_maps_to_its_film_page_slug():
    assert _film_slugs(_HTML) == {
        "Sofijah": "sofijah",
        "Cambodian Beer Dreams": "camdodian-beer-dreams",
        "Queer as punk": "queer-as-punk",
        "The Dating Game": "the-dating-game",
        "Jag ska bara gråta lite först": "jag-ska-bara-grata-lite-forst",
        "HEX": "hex",
        "Sjung för mig Arja!": "sjung-for-mig-arja",
        "The Beauty of Errors": "the-beauty-of-errors",
        "Första blatten på månen": "forsta-blatten-pa-manen",
        "Chasing Time": "chasing-time-qa-och-kortforelasning",
        "My Love, Don\u2019t Cross That River": "my-love-dont-cross-that-river",
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
    assert details["original_languages"] == frozenset({Language.SWEDISH, Language.SPANISH})
    assert details["subtitle_label"] == "Svensk, engelsk text"


def _fetch(session, url):
    if url.endswith("events-screenings"):
        return _HTML
    page = _FIXTURES / f"{url.rsplit('/', 1)[1]}.html"
    return page.read_text() if page.exists() else _FILM_HTML


def _parse(monkeypatch, sizes=None):
    monkeypatch.setattr(doclounge_se, "_fetch", _fetch)
    monkeypatch.setattr(doclounge_se._films, "register", lambda film, session=None: film)
    monkeypatch.setattr(doclounge_se, "_tmdb", lambda title: None)
    monkeypatch.setattr(doclounge_se, "_image_size", lambda session, url: (sizes or {}).get(url))
    return list(doclounge_se.parse())


def test_parse_yields_one_film_per_title_and_keys_every_screening(monkeypatch):
    items = _parse(monkeypatch)
    films = [i for i in items if isinstance(i, Film)]
    screenings = [i for i in items if isinstance(i, Screening)]

    assert [f.key for f in films] == [film_key("doclounge_se", f.title) for f in films]
    assert {s.film_key for s in screenings} == {f.key for f in films}
    assert all(s.film_key for s in screenings)
    # Pages without a fixture of their own are served the "Första blatten på månen" page.
    paged = [s for s in screenings if s.title == "Sofijah"]
    assert {s.version.subtitles.languages for s in paged} == {frozenset({Language.SWEDISH, Language.ENGLISH})}


def test_screenings_carry_the_language_the_film_page_states(monkeypatch):
    screenings = [i for i in _parse(monkeypatch) if isinstance(i, Screening)]
    by_title = {s.title: s for s in screenings}

    assert by_title["Sofijah"].version.audio.languages == frozenset({Language.SWEDISH, Language.SPANISH})
    # The page states no language.
    assert not by_title["Queer as punk"].version.audio.languages


_LOCALS = "https://media.doclounge.se/wp-content/uploads/2024/10/locals-2-e1770900493715.png"


def test_a_film_without_a_published_page_takes_title_and_portrait_poster_from_the_event(monkeypatch):
    film = next(
        i
        for i in _parse(monkeypatch, sizes={_LOCALS: (1414, 2000)})
        if isinstance(i, Film) and i.title == "Doc Lounge Locals"
    )

    assert film.url == ""
    assert film.poster_url == (
        "https://www.doclounge.se/_next/image?url=https%3A%2F%2Fmedia.doclounge.se%2Fwp-content"
        "%2Fuploads%2F2024%2F10%2Flocals-2-e1770900493715.png&w=640&q=75"
    )
    assert film.genres == ["Dokumentär"]


def test_a_landscape_event_image_is_no_poster(monkeypatch):
    # locals-2-e1770900493715.png is 1440x640.
    items = _parse(monkeypatch, sizes={_LOCALS: (1440, 640)})

    assert next(i for i in items if isinstance(i, Film) and i.title == "Doc Lounge Locals").poster_url == ""


def _details(slug: str) -> dict:
    return _film_details((_FIXTURES / f"{slug}.html").read_text())


def test_screening_lists_and_booking_info_are_not_synopsis():
    overview = _details("mordarens-son")["overview"]

    assert overview.startswith("Mördarens son är ett naket och gripande porträtt av Tabaré")
    assert overview.endswith("än de val man försöker göra.")
    for leak in ("Visningar", "biljetter", "Biopremiär", "@", "Speltid"):
        assert leak not in overview


def test_synopsis_follows_its_heading():
    overview = _details("the-beauty-of-errors")["overview"]

    assert overview.startswith("När Tero blev ensamstående pappa")
    for leak in ("Svensk titel", "Bokning", "MALMÖ", "Directors statement"):
        assert leak not in overview


def test_a_synopsis_label_is_stripped():
    assert _details("jag-ska-bara-grata-lite-forst")["overview"].startswith("Småbarnsmorsan Charlotta")


def test_original_title_is_stripped():
    assert _details("queer-as-punk")["title_original"] == "Queer as punk"


def test_age_limit_from_the_fact_list(monkeypatch):
    assert _details("mordarens-son")["age_rating"] == "11"
    assert _details("mordarens-son")["original_languages"] == frozenset({Language.SWEDISH})

    film = next(i for i in _parse(monkeypatch) if isinstance(i, Film) and i.title == "Jag ska bara gråta lite först")
    assert film.age_rating == ""


def test_a_swedish_title_in_parentheses_is_dropped(monkeypatch):
    items = _parse(monkeypatch)
    film = next(i for i in items if isinstance(i, Film) and i.url.endswith("/the-beauty-of-errors"))
    screening = next(i for i in items if isinstance(i, Screening) and i.date == date(2026, 9, 2))

    assert film.title == screening.title == "The Beauty of Errors"
    assert screening.film_key == film.key == film_key("doclounge_se", "The Beauty of Errors")


def test_event_title_suffix_and_info_become_raw_attributes():
    events = _by_date(_HTML)

    assert events[date(2026, 10, 26)][7] == ("Halloweenspecial",)
    assert events[date(2026, 11, 9)][7] == ("Besök av Arja Saijonmaa",)
    # The info repeats the film title before the programme.
    assert events[date(2026, 9, 2)][7] == ("Filmvisning + Regissörsbesök",)
    # A city suffix names no programme.
    assert events[date(2026, 10, 15)][7] == ()
    assert events[date(2026, 10, 1)][7] == ()


def test_screenings_carry_raw_attributes(monkeypatch):
    screenings = [i for i in _parse(monkeypatch) if isinstance(i, Screening)]

    assert next(s for s in screenings if s.date == date(2026, 10, 26)).raw_attributes == ("Halloweenspecial",)
