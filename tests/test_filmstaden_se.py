"""filmstaden.se show mapping."""

import json
from datetime import date, time
from pathlib import Path

from parse.parsers.filmstaden_se import _film, _screening

_FIXTURES = Path(__file__).parent / "fixtures" / "filmstaden_se"
_SHOWS = json.loads((_FIXTURES / "shows.json").read_text())["items"]
_MOVIE = json.loads((_FIXTURES / "movie.json").read_text())


def _map(show):
    return _screening(show, tmdb_id=None, cinema_name="Filmstaden Bergakungen", city="Göteborg")


def test_dubbed_and_subtitled_versions_are_distinguishable():
    dubbed, original = (_map(s) for s in sorted(_SHOWS, key=lambda s: s["time"], reverse=True))

    assert (dubbed.language, dubbed.subtitles) == ("Svenska", "Svenska")
    assert (original.language, original.subtitles) == ("Engelska", "Svenska")


def test_show_fields():
    screening = _map(_SHOWS[0])

    assert screening.title == "Bortglömda ön"
    assert screening.date == date(2026, 9, 26)
    assert screening.time == time(15, 45)
    assert screening.screen == "Salong 5"
    assert screening.format == "Familj"
    assert screening.ticket_url == "https://www.filmstaden.se/bokning/kop/18198ee1-3600-49c5-b213-9dfc1f13529b/"


def test_film_metadata_comes_from_show_and_detail():
    film = _film(_SHOWS[0]["movie"], _MOVIE)

    assert film.key == "filmstaden_se:bortglömda ön"
    assert film.title == "Bortglömda ön"
    assert film.title_original == "Forgotten Island"
    assert film.overview.startswith("Jo och Raissa har varit bästa vänner")
    assert film.runtime == 109
    assert film.genres == ["Äventyr", "Komedi", "Animerat", "Familj"]
    assert film.release_date == "2026-09-25"
    assert film.age_rating == "7 år"
    assert film.url == "https://www.filmstaden.se/film/bortglomda-on/"


def test_poster_is_the_catalog_image_at_display_width():
    film = _film(_SHOWS[0]["movie"])

    assert film.poster_url == (
        "https://catalog.cinema-api.com/cf/images/ncg-images/"
        "59510c056e2445acb50003de1379a263.jpg?w=800&version=F488890EA42856B4EA0930C804BC11BD"
    )


def test_screenings_carry_the_film_key():
    film = _film(_SHOWS[0]["movie"], _MOVIE)
    screening = _screening(
        _SHOWS[0], tmdb_id=None, cinema_name="Filmstaden Bergakungen", city="Göteborg", film_key=film.key
    )

    assert screening.film_key == film.key


def test_unrated_films_have_no_age_rating():
    movie = dict(_SHOWS[0]["movie"], rating={"displayName": "Åldersgräns ej bestämd"})

    assert _film(movie).age_rating == ""
