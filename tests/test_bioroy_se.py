"""bioroy.se programList parsing."""

import json
from pathlib import Path

import pytest

from parse.parsers import bioroy_se
from store import Film

_FIXTURE = Path(__file__).parent / "fixtures" / "bioroy_se" / "program.json"


@pytest.fixture(autouse=True)
def _no_tmdb(monkeypatch):
    monkeypatch.setattr(bioroy_se, "_tmdb", lambda title, runtime=None: None)


@pytest.fixture
def items():
    data = json.loads(_FIXTURE.read_text())
    return list(bioroy_se._parse_program_list(data["props"]["pageProps"]["programList"]))


@pytest.fixture
def screenings(items):
    return [i for i in items if not isinstance(i, Film)]


@pytest.fixture
def films(items):
    return [i for i in items if isinstance(i, Film)]


def test_private_hire_and_sold_out_excluded(screenings):
    assert not any(s.title == "Biosalongen abonnerad" for s in screenings)
    assert not any(s.date.isoformat() == "2026-09-20" for s in screenings)
    assert len(screenings) == 4


def test_languages_from_feature_info(screenings):
    tony = next(s for s in screenings if s.title == "Tony")
    assert tony.language == "ENG"
    assert tony.subtitles == "SV"

    silent = next(s for s in screenings if s.title == "Nosferatu")
    assert silent.language == "STUM"
    assert silent.subtitles == "SV"


def test_screening_fields(screenings):
    s = next(s for s in screenings if s.date.isoformat() == "2026-09-22")
    assert s.title == "Tony"
    assert s.time.strftime("%H:%M") == "18:00"
    assert s.cinema_name == "Bio Roy"
    assert s.city == "Göteborg"
    assert s.ticket_url == "https://secure.tickster.com/dxhamllat43cm82"
    assert s.film_key == "bioroy_se:tony"


def test_film_metadata(films):
    film = next(f for f in films if f.title == "Tony")
    assert film.key == "bioroy_se:tony"
    assert film.overview == (
        "Matt Johnsons hyllade spelfilm om en ung Anthony Bourdain. "
        "En 19-årig Anthony Bourdain reser till Provincetown."
    )
    assert film.runtime == 106
    assert film.genres == ["Drama", "Komedi"]
    assert film.age_rating == "Från 11 år"
    assert film.release_date == "2026-09-18"
    assert film.url == "https://www.bioroy.se/program/tony"


def test_poster_crop_is_rehosted_and_resized(films):
    film = next(f for f in films if f.title == "Tony")
    assert film.poster_url == (
        "https://www.bioroy.se/media/4ahljaau/tony-still.jpg"
        "?format=jpg&quality=100&ranchor=center&width=500&height=750&rmode=crop"
    )


def test_missing_image_leaves_the_poster_empty(films):
    assert next(f for f in films if f.title == "Nosferatu").poster_url == ""


def test_one_film_per_title_and_every_screening_keyed(films, screenings):
    assert [f.title for f in films] == ["Tony", "Nosferatu"]
    keys = {f.key for f in films}
    assert all(s.film_key in keys for s in screenings)
