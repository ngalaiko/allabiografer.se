"""hallundafolketshus.se CaféBio event extraction."""

from datetime import date, time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from parse.parsers import _films, hallundafolketshus_se
from parse.parsers.hallundafolketshus_se import _SOURCE, _details, _events, _title
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
            (),
            False,
        ),
        (
            "Resan till Piemonte",
            date(2026, 9, 29),
            time(13, 0),
            "https://www.hallundafolketshus.se/events/resan-till-piemonte",
            (),
            False,
        ),
        (
            "FÖRSTA BLATTEN PÅ MÅNEN",
            date(2026, 10, 5),
            time(19, 0),
            "https://www.hallundafolketshus.se/events/forsta-blatten-pa-manen",
            (),
            False,
        ),
        (
            "MACBETH",
            date(2026, 10, 17),
            time(19, 0),
            "https://www.hallundafolketshus.se/events/macbeth-2",
            (),
            True,
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
    monkeypatch.setattr(hallundafolketshus_se, "_tmdb", lambda title, **_: None)
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


_ALL = (_FIXTURES / "all.html").read_text()
_COSI = (_FIXTURES / "event_cosi.html").read_text()
_LUST = (_FIXTURES / "event_lust.html").read_text()


def test_event_listing_reads_every_upcoming_screening():
    events = list(_events(_ALL))

    assert [title for title, *_ in events] == [
        "FÖRSTA BLATTEN PÅ MÅNEN",
        "Pressure",
        "Digger",
        "MACBETH",
        "Heart of the Beast",
        "Kärlek över Tanger",
        "Arkipelag",
        "COSì FAN TUTTE",
        "Sense and Sensibility",
        "LUST FOR LIFE",
        "SIMSON OCH DELILA",
        "FLICKAN FRÅN VILDA VÄSTERN",
        "OTELLO",
        "PARSIFAL",
    ]
    assert events[9][1:] == (
        date(2026, 11, 20),
        time(19, 0),
        "https://www.hallundafolketshus.se/events/lust-for-life",
        ("Drive-in-Bio",),
        False,
    )
    assert events[12][1] == date(2027, 4, 24)


def test_event_listing_keeps_same_day_showings():
    item = (
        '<div class="em-event em-item"><div class="em-item-cat">CaféBio</div>'
        '<h3 class="em-item-title"><a href="/events/digger{n}">Digger</a></h3>'
        '<div class="em-date-time">14/10 {t} - 15:09</div></div>'
    )
    html = item.format(n="", t="13:00") + item.format(n="-2", t="18:00")

    assert [(d, t) for _, d, t, *_ in _events(html)] == [
        (date(2026, 10, 14), time(13, 0)),
        (date(2026, 10, 14), time(18, 0)),
    ]


def test_title_takes_the_ticket_casing_of_a_capitalised_title():
    assert _title("COSì FAN TUTTE", "Così fan Tutte - Live på bio från Metropolitan") == "Così fan Tutte"
    assert _title("LUST FOR LIFE", "Lust for life  (Tal: Tyska) (Text: Svenska)") == "Lust for life"
    assert _title("SIMSON OCH DELILA", "Simson och Delila - Live på bio från Metropolitan") == "Simson och Delila"
    assert _title("COSì FAN TUTTE", "") == "Così fan tutte"
    assert _title("MACBETH", "Otello") == "Macbeth"
    assert _title("Heart of the Beast", "heart of the beast") == "Heart of the Beast"


def test_opera_synopsis_leaves_out_credits_and_broadcast_dates():
    overview = _details(_COSI)["overview"]

    assert overview.startswith(
        "Met-säsongen inleds med Mozarts komedi om kärlek. Phelim McDermotts färgstarka uppsättning"
    )
    assert "\n\nCosì fan tutte är ett av Mozarts sista verk" in overview
    assert overview.endswith("Despina.")
    for junk in ("Medverkande", "Fiordiligi –", "Upplev den live på bio", "Speltid", "Regi"):
        assert junk not in overview


def test_opera_synopsis_reads_every_descriptive_paragraph():
    overview = _details(_OPERA)["overview"]

    assert "Live på bio 17 oktober 2026" not in overview
    assert "\n\nEfter tidigare succéer" in overview
    assert overview.endswith("som Banquo.")


def test_film_synopsis_reads_every_paragraph_after_the_facts():
    overview = _details(_FILM)["overview"]

    assert overview.startswith("Dogge Doggelito var rösten")
    assert overview.endswith("fullständigt omöjlig att ignorera.")
    assert overview.count("\n\n") == 2


def test_labelled_facts_sharing_a_paragraph_are_read():
    details = _details(_LUST)

    assert details["genres"] == ["Dokumentär"]
    assert details["runtime"] == 89
    assert details["overview"].startswith("Under en tioårsperiod")


def test_screenings_take_the_ticket_title_casing_and_keep_the_programme_prefix(monkeypatch):
    pages = {
        hallundafolketshus_se._URL: _ALL,
        _SITE + "cosi-fan-tutte": _COSI,
        _SITE + "lust-for-life": _LUST,
        _TICKSTER + "9918cuxmbrv8h8h": (_FIXTURES / "tickster_cosi.html").read_text(),
        _TICKSTER + "wbp6tub1m48jd4x": (_FIXTURES / "tickster_lust.html").read_text(),
    }
    items = _parse(monkeypatch, pages)
    screenings = {s.title: s for s in items if isinstance(s, Screening)}
    films = {f.title for f in items if isinstance(f, Film)}

    assert {"Così fan Tutte", "Lust for life", "Simson och delila"} <= films
    cosi = screenings["Così fan Tutte"]
    assert cosi.ticket_url == _TICKSTER + "9918cuxmbrv8h8h/2026-11-07/cosi-fan-tutte-live-pa-bio-fran-metropolitan"
    assert cosi.film_key == "hallundafolketshus_se:così fan tutte"
    assert screenings["Lust for life"].raw_attributes == ("Drive-in-Bio",)
    assert len(screenings) == 14


def test_synopsis_drops_every_form_of_broadcast_date_sentence():
    page = (
        "<article><p>Puccinis spännande drama återvänder i en ny uppsättning av Richard Jones, den första på 30 år. "
        "Livesänds på bio 23 januari 2027.</p><p>En av dagens ledande tenorer tar sig an titelrollen i operans "
        "största tragedi. Otello livesänds till biografer världen över, 24 april 2027.</p></article>"
    )

    assert _details(page)["overview"] == (
        "Puccinis spännande drama återvänder i en ny uppsättning av Richard Jones, den första på 30 år."
        "\n\nEn av dagens ledande tenorer tar sig an titelrollen i operans största tragedi."
    )


def test_broadcast_lookups_are_restricted_to_the_screening_year(monkeypatch):
    calls: dict[str, int | None] = {}
    monkeypatch.setattr(hallundafolketshus_se, "_SESSION", _Session(_PAGES))
    monkeypatch.setattr(hallundafolketshus_se._films, "register", lambda film, session=None: film)
    monkeypatch.setattr(hallundafolketshus_se, "_tmdb", lambda title, year=None: calls.setdefault(title, year) and None)
    list(hallundafolketshus_se.parse())

    assert calls["Macbeth"] == 2026
    assert calls["Autofiktion"] is None


def test_an_impossible_date_skips_only_that_event(caplog):
    item = (
        '<div class="em-event em-item"><div class="em-item-cat">CaféBio</div>'
        '<h3 class="em-item-title"><a href="/events/{slug}">{slug}</a></h3>'
        '<div class="em-date-time">{day} 13:00 - 15:09</div></div>'
    )
    html = item.format(slug="skottdag", day="29/02") + item.format(slug="digger", day="14/10")

    assert [title for title, *_ in _events(html)] == ["digger"]
    assert "29/02" in caplog.text
