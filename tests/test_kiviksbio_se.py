"""kiviksbio.se event listing extraction."""

from datetime import date, time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from parse.parsers import kiviksbio_se
from parse.parsers.kiviksbio_se import _overview, _runtime, _showtimes, _subtitles
from store import Screening
from store.version import Language

pytestmark = pytest.mark.usefixtures("parser_clock")

_FIXTURES = Path(__file__).parent / "fixtures" / "kiviksbio_se"
_HTML = (_FIXTURES / "evenemang.html").read_text()


def test_showtimes_collapse_whitespace_runs_inside_titles():
    assert [(f.title, d, t, url) for f, d, t, url, _ in _showtimes(_HTML)] == [
        (
            "Autofiktion",
            date(2026, 9, 20),
            time(18, 0),
            "https://www.kiviksbio.se/program/autofiktion/",
        ),
        (
            "Così fan Tutte",
            date(2026, 10, 3),
            time(19, 0),
            "https://www.kiviksbio.se/program/direkt-fran-metropolitanoperan-i-new-york-cosi-fan-tutte/",
        ),
        (
            "Nelly Rapp - Porten till underjorden",
            date(2026, 10, 28),
            time(15, 0),
            "https://www.kiviksbio.se/program/hostlovsfilm-nelly-rapp-porten-till-underjorden/",
        ),
    ]


def test_showtimes_read_item_metadata():
    film = next(f for f, *_ in _showtimes(_HTML))
    assert film.key == "kiviksbio_se:autofiktion"
    assert film.source == "kiviksbio_se"
    # Listing images are landscape banners, unusable as posters.
    assert film.poster_url == ""
    assert film.age_rating == "Barntillåten"
    assert film.runtime == 115
    assert film.url == "https://www.kiviksbio.se/program/autofiktion/"
    # "Film" is the listing's catch-all category, not a genre.
    assert film.genres == []


def test_showtimes_keep_categories_other_than_film_as_genres():
    film = [f for f, *_ in _showtimes(_HTML)][1]
    assert film.genres == ["Opera"]


def test_showtimes_leave_fields_the_item_omits_empty():
    film = [f for f, *_ in _showtimes(_HTML)][2]
    assert (film.poster_url, film.age_rating, film.genres, film.runtime) == ("", "", [], None)


def test_screenings_share_their_film_key():
    films = {f.key for f, *_ in _showtimes(_HTML)}
    assert len(films) == 3


def test_overview_reads_the_event_page_synopsis():
    overview = _overview((_FIXTURES / "autofiktion.html").read_text())
    assert overview.startswith("Oscarsbelönade Pedro Almodóvar är tillbaka")
    assert overview.endswith("gränsen mellan verklighet och fiktion.")


def test_overview_stops_at_the_credits():
    overview = _overview((_FIXTURES / "smugglaren.html").read_text())
    assert overview.endswith("präglat av gamla sår.")


def test_overview_drops_opera_credits_prices_and_side_events():
    overview = _overview((_FIXTURES / "macbeth.html").read_text())
    assert overview.endswith("som Banquo.")
    for junk in ("Regi", "Pris", "Operacirkel", "Textas"):
        assert junk not in overview


def test_subtitles_read_the_event_page():
    assert _subtitles((_FIXTURES / "macbeth.html").read_text())["version"].subtitles.languages == {Language.SWEDISH}
    assert _subtitles((_FIXTURES / "smugglaren.html").read_text())["version"].subtitles.languages is None


def test_showtimes_move_title_prefixes_to_labels():
    html = _HTML + (_FIXTURES / "prefixes.html").read_text()
    assert [(f.title, labels) for f, _, _, _, labels in _showtimes(html)][2:] == [
        ("Nelly Rapp - Porten till underjorden", ("Höstlovsfilm",)),
        ("Resan till Piemonte", ("Extra-visning",)),
        ("De Gaulle- frihetens röst", ("PREMIÄR",)),
    ]
    assert next(labels for *_, labels in _showtimes(html)) == ()


def test_overview_matches_credit_labels_in_any_case():
    page = '<section class="em-event-content"><p>En opera.</p><p>RegI: Darko Tresnjak</p></section>'
    assert _overview(page) == "En opera."


def test_showtimes_move_broadcast_prefixes_to_labels():
    assert [labels for *_, labels in _showtimes(_HTML)][1] == ("Direkt från Metropolitanoperan",)


def test_runtime_from_a_placeholder_end_time_is_unknown():
    assert _runtime(time(14, 0), "23:59") is None
    assert _runtime(time(18, 0), "22:30") == 270


def test_overview_keeps_inline_markup_inside_words():
    page = (
        '<section class="em-event-content"><p>Så här har ingen sett <strong>Tom Cruise t</strong>idigare. '
        "Mästerregissören <strong>Alejandro Inàritu</strong> (<em>Birdman, Babel,</em> m.fl.) "
        "regisserar <em>Otello</em>.</p><p>Andra<br/>stycket.</p><p><strong>Regi: X</strong></p></section>"
    )
    assert _overview(page) == (
        "Så här har ingen sett Tom Cruise tidigare. "
        "Mästerregissören Alejandro Inàritu (Birdman, Babel, m.fl.) regisserar Otello."
        "\n\nAndra stycket."
    )


def test_overview_drops_spaces_before_punctuation():
    page = (
        '<section class="em-event-content">'
        "<p>Operans största tragedi<strong> – Otello .<br/></strong>Verdis Otello.</p></section>"
    )
    assert _overview(page) == "Operans största tragedi – Otello. Verdis Otello."


class _Session:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def get(self, url, timeout=None):
        if url not in self.pages:
            raise requests.ConnectionError(url)
        return SimpleNamespace(text=self.pages[url], ok=True, raise_for_status=lambda: None)


def _parse(monkeypatch, pages: dict[str, str], tmdb=lambda title, runtime=None, year=None: None) -> list:
    monkeypatch.setattr(kiviksbio_se._http, "session", lambda *a: _Session(pages))
    monkeypatch.setattr(kiviksbio_se._films, "register", lambda film, session=None: film)
    monkeypatch.setattr(kiviksbio_se, "_tmdb", tmdb)
    return list(kiviksbio_se.parse())


def _lookups(monkeypatch, tmdb_ids: dict | None = None) -> list[tuple]:
    calls = []

    def tmdb(title, runtime=None, year=None):
        calls.append((title, runtime, year))
        return (tmdb_ids or {}).get((title, runtime, year))

    _parse(monkeypatch, {kiviksbio_se._URL: _HTML}, tmdb)
    return calls


def test_broadcast_lookups_are_restricted_to_the_screening_year(monkeypatch):
    assert {(t, y) for t, _, y in _lookups(monkeypatch)} == {
        ("Autofiktion", None),
        ("Così fan Tutte", 2026),
        ("Nelly Rapp - Porten till underjorden", None),
    }


def test_lookup_passes_the_runtime_then_falls_back_to_the_title(monkeypatch):
    calls = _lookups(monkeypatch)
    assert ("Autofiktion", 115, None) in calls
    assert ("Autofiktion", None, None) in calls


def test_lookup_by_runtime_wins(monkeypatch):
    calls = _lookups(monkeypatch, {("Autofiktion", 115, None): 1})
    assert ("Autofiktion", None, None) not in calls


def test_a_failed_detail_page_keeps_the_screenings(monkeypatch, caplog):
    items = _parse(monkeypatch, {kiviksbio_se._URL: _HTML})
    assert len([i for i in items if isinstance(i, Screening)]) == 3
    assert "autofiktion" in caplog.text


def _item(date_text: str) -> str:
    return (
        '<div class="em-item"><h3 class="em-item-title"><a href="https://www.kiviksbio.se/program/x/">X</a></h3>'
        f'<div class="em-event-date">{date_text}</div></div>'
    )


def test_showtimes_read_months_in_any_case_and_length():
    html = _item("lördag 3 Okt kl 19:00") + _item("lördag 3 oktober kl 19:00") + _item("onsdag 2 DECEMBER kl 18:00")
    assert [d for _, d, *_ in _showtimes(html)] == [date(2026, 10, 3), date(2026, 10, 3), date(2026, 12, 2)]


def test_showtimes_warn_on_an_unparseable_date(caplog):
    assert list(_showtimes(_item("lördag 3 foo kl 19:00"))) == []
    assert "lördag 3 foo kl 19:00" in caplog.text
