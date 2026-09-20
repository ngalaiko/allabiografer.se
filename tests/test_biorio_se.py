"""biorio.se calendar showtime extraction."""

from contextlib import contextmanager
from datetime import date, time
from pathlib import Path
from types import SimpleNamespace

from parse.parsers import biorio_se
from parse.parsers.biorio_se import _film_details, _film_urls, _showtimes
from store import Film, Screening, film_key

_HTML = (Path(__file__).parent / "fixtures" / "biorio_se" / "kalender.html").read_text()


def test_showtimes_read_time_and_screen_from_the_info_block():
    assert list(_showtimes(_HTML)) == [
        (
            "Practical Magic: Family Legacy",
            date(2026, 9, 20),
            time(15, 20),
            "https://www.biorio.se/sv/boka/2706",
            "Salong 1",
        ),
        ("In the Mood for Love", date(2026, 9, 20), time(18, 0), "https://www.biorio.se/sv/boka/2533", "Salong 1"),
        ("Pressure", date(2026, 9, 20), time(20, 10), "https://www.biorio.se/sv/boka/2670", "Salong 1"),
        ("Tony", date(2026, 9, 21), time(15, 45), "https://www.biorio.se/sv/boka/2689", "Salong 1"),
        ("Medan vi faller", date(2026, 9, 21), time(18, 0), "https://www.biorio.se/sv/boka/2612", "Salong 1"),
        (
            "Oasis: Don't Look Back in Anger",
            date(2026, 9, 21),
            time(20, 10),
            "https://www.biorio.se/sv/boka/2748",
            "Salong 1",
        ),
    ]


_FILM_HTML = (Path(__file__).parent / "fixtures" / "biorio_se" / "film.html").read_text()

_POSTER = (
    "https://www.biorio.se/_next/image"
    "?url=https%3A%2F%2Frio.ams3.digitaloceanspaces.com%2Fmovies%2Fmovies%2F4992"
    "%2Fposters%2F1742812872762-if4u2o.jpg&w=640&q=85"
)


def test_the_calendar_title_links_to_the_film_page():
    assert _film_urls(_HTML)["In the Mood for Love"] == "https://www.biorio.se/sv/filmer/in-the-mood-for-love"
    assert len(_film_urls(_HTML)) == 6


def test_film_details_read_poster_synopsis_runtime_genres_and_year():
    details = _film_details(_FILM_HTML)

    assert details["poster_url"] == _POSTER
    assert details["overview"].startswith("Två par flyttar samtidigt in i samma fastighet")
    assert details["runtime"] == 98
    assert details["genres"] == ["Drama", "Romantik"]
    # The page states a year, never a full release date.
    assert details["release_date"] == "2000"


def test_parse_yields_one_film_per_title_and_keys_every_screening(monkeypatch):
    monkeypatch.setattr(biorio_se, "browser_page", lambda: _page(_HTML))
    monkeypatch.setattr(biorio_se, "_details", lambda session, url: _film_details(_FILM_HTML))
    monkeypatch.setattr(biorio_se._films, "register", lambda film, session=None: film)
    monkeypatch.setattr(biorio_se, "_tmdb", lambda title: None)

    items = list(biorio_se.parse())
    films = [i for i in items if isinstance(i, Film)]
    screenings = [i for i in items if isinstance(i, Screening)]

    assert [f.key for f in films] == [film_key("biorio_se", f.title) for f in films]
    assert len(films) == 6
    assert {s.film_key for s in screenings} == {f.key for f in films}


@contextmanager
def _page(html: str):
    yield SimpleNamespace(goto=lambda *a, **kw: None, content=lambda: html)
