"""bio.se cinema records and session payloads."""

import json
from datetime import date, time
from pathlib import Path

from parse.parsers.bio_se import _age_rating, _showtimes, _ticket_url, _venue
from store import Venue

_FIXTURES = Path(__file__).parent / "fixtures" / "bio_se"
_CINEMAS = {c["title"]: c for c in json.loads((_FIXTURES / "cinemas.json").read_text())["cinemas"]}


def _films(name: str) -> dict:
    return json.loads((_FIXTURES / f"{name}-films.json").read_text())


def test_venue_trims_padded_city_and_address():
    assert _venue(_CINEMAS["Alvesta Bio Thalia"]) == Venue(
        name="Alvesta Bio Thalia", city="Alvesta", address="Allbogatan 17"
    )
    assert _venue(_CINEMAS["Falköping Cosmorama"]) == Venue(
        name="Falköping Cosmorama", city="Falköping", address="Sankt Olofsgatan 20"
    )


def test_venue_skips_records_without_a_location():
    assert _venue(_CINEMAS["Enter Details"]) is None
    assert _venue(_CINEMAS["Gåxsjö Bio"]) is None


def _rows(name: str) -> list[tuple]:
    return [(f.title, *rest) for f, *rest in _showtimes(_films(name))]


def test_showtimes_unescape_entities_in_titles():
    titles = {t for t, *_ in _rows("falkoping-cosmorama")}
    assert "Minioner & Monster SV.tal" in titles


def test_showtimes_read_session_fields():
    assert _rows("falkoping-cosmorama") == [
        (
            "Spider-Man: Brand New Day",
            date(2026, 9, 22),
            time(18, 30),
            "https://www.eurostar.se/Boka/f284624",
            "Screen 1",
            "",
            "Engelska",
            "Svenska",
        ),
        (
            "Spider-Man: Brand New Day",
            date(2026, 10, 9),
            time(19, 15),
            "https://www.eurostar.se/Boka/f285137",
            "Screen 3",
            "",
            "Engelska",
            "Svenska",
        ),
        (
            "Minioner & Monster SV.tal",
            date(2026, 10, 4),
            time(17, 0),
            "https://www.eurostar.se/Boka/f285109",
            "Screen 2",
            "",
            "Svenska",
            "",
        ),
    ]


def test_showtimes_trim_padded_subtitles():
    assert _rows("stockholm-bio-aspen") == [
        (
            "The Lost Boys",
            date(2026, 10, 31),
            time(20, 15),
            "https://biljetter.bioaspen.se/#/book/57503",
            "Aspen",
            "",
            "Eng.",
            "Sv.",
        )
    ]


def test_ticket_url_absolutises_site_relative_payment_links():
    assert _ticket_url("/bokning/cinemaId/5/sessionId/20077") == "https://bio.se/bokning/cinemaId/5/sessionId/20077"
    assert _ticket_url("https://www.eurostar.se/Boka/f284624") == "https://www.eurostar.se/Boka/f284624"
    assert _ticket_url("") == ""


def test_film_reads_metadata_and_strips_escaped_markup():
    film, *_ = next(iter(_showtimes(_films("falkoping-cosmorama"))))
    assert film.key == "bio_se:spider man brand new day"
    assert film.source == "bio_se"
    assert film.overview.startswith("Efter rekordsuccén inleder Spider-Man: Brand New Day")
    assert "<br>" not in film.overview
    assert film.runtime == 150
    assert film.genres == ["Adventure", "Action"]
    assert film.age_rating == "Från 11 år"
    assert film.url == "https://bio.se/movie/42156"
    assert film.poster_url.endswith("spider-man-brandnewday_reflection_144")


def test_film_leaves_unstated_fields_empty():
    films = {f.title: f for f, *_ in _showtimes(_films("falkoping-cosmorama"))}
    film = films["Minioner & Monster SV.tal"]
    assert (film.overview, film.runtime, film.genres, film.age_rating, film.poster_url) == ("", None, [], "", "")


def test_film_normalises_abbreviated_ratings():
    film, *_ = next(iter(_showtimes(_films("stockholm-bio-aspen"))))
    assert film.age_rating == "Barntillåten"
    assert _age_rating("Från 7år") == "Från 7 år"
    assert _age_rating("7+") == "Från 7 år"
    assert _age_rating("Ej angivet") == ""


def test_screenings_share_their_film_key():
    keys = {f.key for f, *_ in _showtimes(_films("falkoping-cosmorama"))}
    assert keys == {"bio_se:spider man brand new day", "bio_se:minioner monster sv tal"}
