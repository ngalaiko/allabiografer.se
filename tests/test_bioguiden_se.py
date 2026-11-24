"""Bioguiden programmes, booking fallbacks and incomplete-import protection."""

import sys
from datetime import date, time
from pathlib import Path

import pytest
import requests
from bs4 import BeautifulSoup

import parse
from parse.parsers import bioguiden_se
from store import Film, Screening, Venue, read_screenings, write_screenings
from store.version import AudioKind, Dimension

_FIXTURES = Path(__file__).parent / "fixtures" / "bioguiden_se"
_SITES = bioguiden_se._SITES
_LYCKSELE, _VISIR = list(_SITES)[:2]
_NO_RESULTS = '<div id="NoResultsLiteral">Inga filmer kunde hittas</div>'


@pytest.fixture
def pages(monkeypatch):
    pages = {
        _LYCKSELE: (_FIXTURES / "lycksele.html").read_bytes(),
        _VISIR: (_FIXTURES / "visir.html").read_bytes(),
    }

    class Session:
        def get(self, url, timeout=None):
            response = requests.Response()
            response.status_code = 200 if url in pages else 503
            response.url = url
            response._content = pages.get(url, b"")
            return response

    monkeypatch.setattr(bioguiden_se._http, "session", Session)
    monkeypatch.setattr(bioguiden_se._films, "register", lambda film, **kwargs: film)
    monkeypatch.setattr(bioguiden_se, "_tmdb", lambda title, **kwargs: None)
    monkeypatch.setattr(bioguiden_se, "_SITES", {url: bioguiden_se._SITES[url] for url in pages})
    return pages


def test_imports_both_programmes_with_metadata_and_booking_fallbacks(pages):
    items = list(bioguiden_se.parse())
    screenings = [item for item in items if isinstance(item, Screening)]
    films = {item.title: item for item in items if isinstance(item, Film)}
    venues = [item for item in items if isinstance(item, Venue)]
    assert venues == [
        Venue(name="Medborgarhus Bio", city="Lycksele", address="Norra Torggatan 14"),
        Venue(name="Leksand Visir Bio", city="Leksand", address="Faluvägen 16"),
    ]
    assert len([s for s in screenings if s.city == "Lycksele"]) == 22
    assert len([s for s in screenings if s.city == "Leksand"]) == 12
    # Three films occur in both programmes: Arne, Hunger Games and Jakten.
    assert len([item for item in items if isinstance(item, Film)]) == len(films) == 19
    arne = [s for s in screenings if s.title == "Arne Goes to Space" and s.city == "Lycksele"]
    assert [(s.date, s.time) for s in arne] == [
        (date(2026, 11, 20), time(13)),
        (date(2026, 11, 20), time(19)),
        (date(2026, 11, 22), time(19)),
        (date(2026, 11, 24), time(19)),
    ]
    assert arne[0].ticket_url == "https://www.tickster.com/sv/events/D58YZTCY2TUK10J"
    assert arne[1].ticket_url == "https://www.tickster.com/sv/events/C1F4VTKJ1AM46JN"
    visir = [s for s in screenings if s.title == "Jävla karlar"]
    assert [(s.date, s.time, s.ticket_url) for s in visir] == [
        (date(2026, 11, 16), time(19), _VISIR),
        (date(2026, 11, 18), time(14), _VISIR),
    ]
    assert films["Arne Goes to Space"].runtime == 102
    assert films["Arne Goes to Space"].age_rating == "Från 7 år"
    assert films["Arne Goes to Space"].overview.startswith("Bröderna Arne (Lennart Jähkel)")
    assert "Visningar" not in films["Arne Goes to Space"].overview
    assert films["Arne Goes to Space"].poster_url == (
        "https://www.bioguiden.se/image.aspx?id=38f9fb0e-3064-4f85-9327-813dc50c80f6"
    )
    assert films["Arne Goes to Space"].url.startswith("https://www.bioguiden.se/filmfokus.aspx?movieid=")
    assert films["Dune: Part Three"].runtime is None
    assert films["Dune: Part Three"].age_rating == ""
    assert all(s.film_key == films[s.title].key for s in screenings)
    # Film-level accessibility icons confirm neither a screening service nor its version.
    assert all(not s.accessibility.features for s in screenings)
    assert all(s.version.audio.kind is AudioKind.UNKNOWN for s in screenings)
    assert all(s.version.subtitles.languages is None for s in screenings)
    assert all(s.presentation.dimension is Dimension.UNKNOWN for s in screenings)
    assert all(s.screen == "" for s in screenings)


def test_sankt_jorgen_uses_direct_tickster_checkout(pages, monkeypatch):
    url = next(url for url, venue in _SITES.items() if venue.name == "Sankt Jörgen Park Biografen")
    programme = BeautifulSoup(pages[_LYCKSELE], "html.parser")
    programme.select_one("#SearchTheatreDropDown option[selected]")["value"] = (
        "227|c12ff623-32f1-41a8-9288-c215cc1de994"
    )
    programme.select_one("#biografinfo h2").string = "Sankt Jörgen Park Biografen"
    block = programme.select_one("#SearchResultDetails .resultat")
    for other_block in programme.select("#SearchResultDetails .resultat")[1:]:
        other_block.decompose()
    block.select_one("h3").string = "Jävla karlar"
    block.select_one("[id=biografrepertoire] > ul").clear()
    rows = block.select_one("[id=biografrepertoire] > ul")
    rows.append(
        BeautifulSoup(
            "<li>2026-11-20 19:00 Sankt Jörgen Park Biografen "
            '<a href="/redirect.aspx?url=https%3A%2F%2Fwww.tickster.com%2Fsv%2Fevents%2FL7RBGCF7G54A45X">Boka</a></li>'
            "<li>2026-11-27 19:00 Sankt Jörgen Park Biografen "
            '<a href="https://example.com/checkout">Boka</a></li>',
            "html.parser",
        )
    )
    pages[url] = programme.encode()
    monkeypatch.setattr(bioguiden_se, "_SITES", {url: _SITES[url]})

    screenings = [item for item in bioguiden_se.parse() if isinstance(item, Screening)]
    assert [(s.date, s.time, s.ticket_url) for s in screenings] == [
        (date(2026, 11, 20), time(19), "https://secure.tickster.com/l7rbgcf7g54a45x"),
        (date(2026, 11, 27), time(19), "https://example.com/checkout"),
    ]


@pytest.mark.parametrize("booked_first", [False, True])
def test_expanded_programmes_preserve_towns_and_simultaneous_auditoriums(pages, monkeypatch, booked_first):
    selected = {}
    for city, fixture in [("Kristinehamn", "kristinehamn"), ("Arbrå", "arbra"), ("Vuollerim", "vuollerim")]:
        url, venue = next((url, venue) for url, venue in _SITES.items() if venue.city == city)
        selected[url] = venue
        pages[url] = (_FIXTURES / f"{fixture}.html").read_bytes()
        if city == "Kristinehamn" and booked_first:
            soup = BeautifulSoup(pages[url], "html.parser")
            blues = [
                block
                for block in soup.select(".resultat")
                if block.select_one("h3").get_text(strip=True) == "Blues Brothers"
            ]
            blues[0].insert_before(blues[1].extract())
            pages[url] = str(soup).encode()
    monkeypatch.setattr(bioguiden_se, "_SITES", selected)
    items = list(bioguiden_se.parse())
    screenings = [item for item in items if isinstance(item, Screening)]
    assert {s.city for s in screenings} == {"Kristinehamn", "Arbrå", "Vuollerim"}
    assert len([s for s in screenings if s.city == "Arbrå"]) == 8
    assert len([s for s in screenings if s.city == "Vuollerim"]) == 2
    assert all(s.screen == "" for s in screenings if s.city != "Kristinehamn")
    kristinehamn = [s for s in screenings if s.city == "Kristinehamn"]
    assert len(kristinehamn) == 33
    assert {s.screen for s in kristinehamn} == {"Salong Bro", "Salong Grand", "Första Klass"}
    simultaneous = [
        s
        for s in kristinehamn
        if s.title == "The Hunger Games: Sunrise on the reaping"
        and s.date == date(2026, 11, 22)
        and s.time == time(19, 30)
    ]
    assert {s.screen for s in simultaneous} == {"Salong Grand", "Första Klass"}
    blues = [s for s in kristinehamn if s.title == "Blues Brothers"]
    assert len(blues) == 1
    assert (blues[0].date, blues[0].time, blues[0].screen) == (date(2026, 11, 14), time(18), "Salong Bro")
    assert (
        blues[0].ticket_url
        == "https://kristinehamnsbio.internetbokningen.com/chap/ajax/tomovie@salongnr=0002&tid=18:00&datum=2026-11-14"
    )
    assert next(item for item in items if isinstance(item, Film) and item.title == "Blues Brothers").poster_url == ""


def test_remaining_programmes_distinguish_cinema_aliases_from_named_halls(pages, monkeypatch):
    selected = {}
    for prefix, fixture in [
        ("20cc1667", "gunnarsbyn"),
        ("cd62cdad", "varberg-filmklubb"),
        ("93a5d081", "varberg"),
    ]:
        url, venue = next((url, venue) for url, venue in _SITES.items() if prefix in url)
        selected[url] = venue
        pages[url] = (_FIXTURES / f"{fixture}.html").read_bytes()
    # Keep historical hall parsing covered without re-enabling this venue in production.
    aspen_url = bioguiden_se._BASE + "biografer.aspx?cityid=1000&theatreid=122103ca-575b-4712-becd-be8e3c075587"
    assert aspen_url not in _SITES
    selected[aspen_url] = Venue(name="Aspen", city="Stockholm", address="Hägerstensvägen 100")
    pages[aspen_url] = (_FIXTURES / "aspen.html").read_bytes()
    monkeypatch.setattr(bioguiden_se, "_SITES", selected)
    items = list(bioguiden_se.parse())
    screenings = [item for item in items if isinstance(item, Screening)]
    assert len(screenings) == 29
    gunnarsbyn = [s for s in screenings if s.city == "Gunnarsbyn"]
    assert len(gunnarsbyn) == 8
    assert all(s.cinema_name == "Gunnarsbyn Saga Bio" and not s.screen for s in gunnarsbyn)
    aspen = [s for s in screenings if s.cinema_name == "Aspen"]
    assert len(aspen) == 17
    assert {s.screen for s in aspen} == {"Aspen", "Lusoperan"}
    arkipelag = [s for s in aspen if s.title == "Arkipelag"]
    assert (arkipelag[0].date, arkipelag[0].time, arkipelag[0].screen) == (date(2026, 11, 14), time(16, 30), "Aspen")
    assert (arkipelag[1].date, arkipelag[1].time, arkipelag[1].screen) == (
        date(2026, 11, 15),
        time(20, 15),
        "Lusoperan",
    )
    varberg = [s for s in screenings if s.city == "Varberg"]
    assert {s.title for s in varberg} == {"För döva öron", "Jävla karlar", "Wicker", "Om ingen går i fällan"}
    assert all(s.cinema_name == "Varbergs Teater" and not s.screen for s in varberg)
    assert {item.address for item in items if isinstance(item, Venue) and item.city == "Varberg"} == {
        "Engelbrektsgatan 7"
    }
    child_film = next(s for s in varberg if s.title == "Om ingen går i fällan")
    assert (child_film.date, child_film.time) == (date(2026, 11, 28), time(12))
    assert child_film.ticket_url == "https://www.tickster.com/sv/events/ZF6B63PNJZ9X6FR"


@pytest.mark.parametrize("fallback_selection", [False, True])
def test_empty_programme_does_not_block_other_cinemas(pages, fallback_selection):
    soup = BeautifulSoup(pages[_LYCKSELE], "html.parser")
    soup.select_one("#SearchResultDetails").replace_with(BeautifulSoup(_NO_RESULTS, "html.parser"))
    if fallback_selection:
        soup.select_one("#SearchTheatreDropDown option[selected]")["value"] = "11|4395ab77-fc3f-4da5-9e62-cd6ddea0cf1d"
    pages[_LYCKSELE] = soup.encode()

    items = list(bioguiden_se.parse())

    assert {item.city for item in items if isinstance(item, Venue)} == {"Lycksele", "Leksand"}
    screenings = [item for item in items if isinstance(item, Screening)]
    assert len(screenings) == 12
    assert {item.city for item in screenings} == {"Leksand"}


@pytest.mark.parametrize(
    "failure",
    [
        "http",
        "wrong_cinema",
        "wrong_empty_cinema",
        "mostly_empty",
        "missing_programme",
        "missing_showtimes",
        "invalid_time",
    ],
)
def test_failed_second_cinema_preserves_the_stored_programme(pages, monkeypatch, tmp_path, failure):
    db = tmp_path / "programme.db"
    previous = Screening(
        tmdb_id=None,
        title="Previously imported film",
        city="Leksand",
        cinema_name="Leksand Visir Bio",
        date=date(2099, 1, 2),
        time=time(20),
        ticket_url=_VISIR,
    )
    write_screenings([previous], path=db, source="bioguiden_se")
    before = read_screenings(path=db)
    if failure == "http":
        del pages[_VISIR]
    elif failure == "wrong_cinema":
        pages[_VISIR] = pages[_LYCKSELE]
    elif failure == "wrong_empty_cinema":
        soup = BeautifulSoup(pages[_VISIR], "html.parser")
        soup.select_one("#SearchResultDetails").replace_with(BeautifulSoup(_NO_RESULTS, "html.parser"))
        soup.select_one("#SearchTheatreDropDown option[selected]")["value"] = ""
        soup.select_one("#biografadress address").string = "Wrong street 99"
        pages[_VISIR] = soup.encode()
    elif failure == "mostly_empty":
        for url, html in pages.items():
            soup = BeautifulSoup(html, "html.parser")
            soup.select_one("#SearchResultDetails").replace_with(BeautifulSoup(_NO_RESULTS, "html.parser"))
            pages[url] = soup.encode()
    elif failure == "missing_programme":
        pages[_VISIR] = pages[_VISIR].replace(b'id="SearchResultDetails"', b'id="changed"')
    elif failure == "missing_showtimes":
        pages[_VISIR] = pages[_VISIR].replace(b'id="biografrepertoire"', b'id="changed"')
    else:
        pages[_VISIR] = pages[_VISIR].replace(b"2026-11-15 15:00", b"2026-11-15 25:00")
    monkeypatch.setattr(sys, "argv", ["parse", "--output", str(db), "bioguiden_se"])
    with pytest.raises((ValueError, requests.HTTPError)):
        parse.main()
    assert read_screenings(path=db) == before
