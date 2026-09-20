"""kiviksbio.se event listing extraction."""

from datetime import date, time
from pathlib import Path

from parse.parsers.kiviksbio_se import _overview, _showtimes

_FIXTURES = Path(__file__).parent / "fixtures" / "kiviksbio_se"
_HTML = (_FIXTURES / "evenemang.html").read_text()


def test_showtimes_collapse_whitespace_runs_inside_titles():
    assert [(f.title, d, t, url) for f, d, t, url in _showtimes(_HTML)] == [
        (
            "Autofiktion",
            date(2026, 9, 20),
            time(18, 0),
            "https://www.kiviksbio.se/program/autofiktion/",
        ),
        (
            "Direkt från Metropolitanoperan: Così fan Tutte",
            date(2026, 10, 3),
            time(19, 0),
            "https://www.kiviksbio.se/program/direkt-fran-metropolitanoperan-i-new-york-cosi-fan-tutte/",
        ),
        (
            "Höstlovsfilm! Nelly Rapp - Porten till underjorden",
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
    assert overview.endswith("Land: Spanien")
