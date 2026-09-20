"""soderkopingsbio.se program row extraction."""

import json
from contextlib import contextmanager
from datetime import date, time
from pathlib import Path
from types import SimpleNamespace

from parse.parsers import soderkopingsbio_se
from parse.parsers.soderkopingsbio_se import _film_details, _film_slugs, _showtimes
from store import Film, Screening, film_key

_HTML = (Path(__file__).parent / "fixtures" / "soderkopingsbio_se" / "program.html").read_text()

_TICKETS = "https://secure.tickster.com/d8fnyrrcl72fv8p"


def test_showtimes_read_tickster_rows_with_screen_and_audio_tags():
    assert list(_showtimes(_HTML)) == [
        (
            "Bus och mysterier med Alfons Åberg",
            date(2026, 9, 20),
            time(14, 0),
            _TICKETS,
            "Sal 1",
            "Svenska",
            "Svenska",
        ),
        ("Superhunden Charlie", date(2026, 9, 20), time(15, 0), _TICKETS, "Sal 1", "Svenska", "Svenska"),
        ("Tony", date(2026, 9, 20), time(18, 30), _TICKETS, "Sal 1", "Engelska", "Svenska"),
        ("Stora biodagen 2026", date(2026, 9, 20), time(23, 59), _TICKETS, "Sal 1", "", ""),
        ("Tony", date(2026, 9, 23), time(18, 30), _TICKETS, "Sal 1", "Engelska", "Svenska"),
    ]


_MOVIE = json.loads((Path(__file__).parent / "fixtures" / "soderkopingsbio_se" / "movie.json").read_text())


def test_the_program_title_links_to_the_movie_slug():
    assert _film_slugs(_HTML) == {
        "Bus och mysterier med Alfons Åberg": "bus-och-mysterier-med-alfons-aberg-(svtxt)-(svtal)_1",
        "Superhunden Charlie": "superhunden-charlie-(svtxt)-(sv-tal)_2",
        "Tony": "tony-(svtxt)-(engtal)_3",
        "Stora biodagen 2026": "stora-biodagen-2026_0",
    }


def test_film_details_read_the_movie_api_record():
    details = _film_details(_MOVIE)

    assert details["poster_url"] == (
        "https://cdn.incode.se/content/61BB6B68-BF8C-4771-A803-A58F5B6DDE62.jpg?resize=600x900"
    )
    assert details["overview"].startswith("En 19-årig Anthony Bourdain")
    assert details["runtime"] == 106
    assert details["age_rating"] == "11"
    assert details["title_original"] == "Tony"
    assert details["release_date"] == "2026-09-18"
    # The API carries a genre field, always null.
    assert details["genres"] == []


def test_barntillaten_becomes_btl_and_an_unrated_event_no_rating():
    assert _film_details({"rating": "Barntillåten"})["age_rating"] == "BTL"
    assert _film_details({"rating": "Ej granskad"})["age_rating"] == ""


def test_parse_yields_one_film_per_title_and_keys_every_screening(monkeypatch):
    monkeypatch.setattr(soderkopingsbio_se, "browser_page", lambda: _page(_HTML))
    monkeypatch.setattr(soderkopingsbio_se, "_details", lambda session, url: _film_details(_MOVIE))
    monkeypatch.setattr(soderkopingsbio_se._films, "register", lambda film, session=None: film)
    monkeypatch.setattr(soderkopingsbio_se, "_tmdb", lambda title: None)

    items = list(soderkopingsbio_se.parse())
    films = [i for i in items if isinstance(i, Film)]
    screenings = [i for i in items if isinstance(i, Screening)]

    assert [f.key for f in films] == [film_key("soderkopingsbio_se", f.title) for f in films]
    assert len(films) == 4
    assert {s.film_key for s in screenings} == {f.key for f in films}


@contextmanager
def _page(html: str):
    yield SimpleNamespace(goto=lambda *a, **kw: None, content=lambda: html)
