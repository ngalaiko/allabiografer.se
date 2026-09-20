"""fhbracke.se programme and film page extraction."""

from datetime import date, time
from pathlib import Path

from parse.parsers import _films
from parse.parsers.fhbracke_se import _SOURCE, _details, _listings

_FIXTURES = Path(__file__).parent / "fixtures" / "fhbracke_se"
_BIO = (_FIXTURES / "bio.html").read_text()
_FILM = (_FIXTURES / "film.html").read_text()


def test_programme_yields_showtimes_with_posters():
    shows = list(_listings(_BIO))

    assert [s["title"] for s in shows] == ["The Dog Stars", "De Gaulle: Motståndets pris"]
    assert shows[0]["date"] == date(2026, 9, 20)
    assert shows[0]["time"] == time(19, 0)
    assert shows[0]["url"] == "https://fhbracke.se/film/the-dog-stars/"
    assert shows[0]["poster_url"].endswith("GATOR_TEASER2_POSTER_SWEDEN_1440x2057_-717x1024.jpg")


def test_relative_film_links_become_absolute():
    shows = list(_listings(_BIO))

    assert shows[1]["url"] == "https://fhbracke.se/film/de-gaulle-motstandets-pris/"


def test_site_chrome_is_not_taken_for_a_poster():
    assert all("BrackeFH" not in s["poster_url"] for s in _listings(_BIO))


def test_film_page_carries_synopsis_runtime_and_age_rating():
    details = _details(_FILM)

    assert details["runtime"] == 118
    assert details["age_rating"] == "Fr.15 år"
    assert details["overview"].startswith("Från Ridley Scott")
    assert "Vi är ett gäng ungdomar" not in details["overview"]


def test_listing_and_details_combine_into_a_film():
    show = next(iter(_listings(_BIO)))
    film = _films.make(_SOURCE, show["title"], url=show["url"], poster_url=show["poster_url"], **_details(_FILM))

    assert film.key == "fhbracke_se:the dog stars"
    assert film.runtime == 118
    assert film.age_rating == "Fr.15 år"
    assert film.poster_url == show["poster_url"]
    assert film.url == "https://fhbracke.se/film/the-dog-stars/"
