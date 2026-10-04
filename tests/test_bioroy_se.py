"""bioroy.se programList parsing."""

import json
from pathlib import Path

import pytest

from parse.parsers import bioroy_se
from store import Film
from store.version import AudioKind, Language

_FIXTURE = Path(__file__).parent / "fixtures" / "bioroy_se" / "program.json"
_FILM_HTML = (Path(__file__).parent / "fixtures" / "bioroy_se" / "film.html").read_text()
_DIGGER_POSTER = "https://www.bioroy.se/media/0qydhymd/digger_aff1.jpg?width=500&height=750&rmode=max&format=jpg"


@pytest.fixture(autouse=True)
def _no_tmdb(monkeypatch):
    monkeypatch.setattr(bioroy_se, "_tmdb", lambda title, runtime=None: None)


@pytest.fixture
def items():
    data = json.loads(_FIXTURE.read_text())
    pl = data["props"]["pageProps"]["programList"]
    return list(bioroy_se._parse_program_list(pl, posters={14714: _DIGGER_POSTER}))


@pytest.fixture
def screenings(items):
    return [i for i in items if not isinstance(i, Film)]


@pytest.fixture
def films(items):
    return [i for i in items if isinstance(i, Film)]


def test_private_hire_excluded(screenings):
    assert not any(s.title == "Biosalongen abonnerad" for s in screenings)
    assert len(screenings) == 10


def test_sold_out_shows_are_kept(screenings):
    assert any(s.title == "Tony" and s.date.isoformat() == "2026-09-20" for s in screenings)


def test_languages_from_feature_info(screenings):
    tony = next(s for s in screenings if s.title == "Tony")
    assert tony.version.audio.languages == frozenset({Language.ENGLISH})
    assert tony.version.subtitles.languages == frozenset({Language.SWEDISH})

    silent = next(s for s in screenings if s.title == "Nosferatu")
    assert silent.version.audio.kind is AudioKind.SILENT
    assert silent.version.subtitles.languages == frozenset({Language.SWEDISH})


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
    assert [f.title for f in films] == [
        "Tony",
        "Nosferatu",
        "Sing Along: The Rocky Horror Picture Show",
        "Arkipelag",
        "Digger",
        "Vår jord",
    ]
    keys = {f.key for f in films}
    assert all(s.film_key in keys for s in screenings)


def test_themes_become_raw_attributes(screenings):
    by_title = {s.title: s for s in screenings}
    assert by_title["Nosferatu"].raw_attributes == ("Stumfilm med livemusik", "Klassiker")
    assert by_title["Sing Along: The Rocky Horror Picture Show"].raw_attributes == ("Sing & Party Along", "Klassiker")
    assert by_title["Tony"].raw_attributes == ()


def test_a_silent_film_theme_marks_the_audio_silent():
    data = json.loads(_FIXTURE.read_text())
    pl = data["props"]["pageProps"]["programList"]
    next(f for f in pl["features"] if f["id"] == 18990)["info"]["audioLanguage"] = ""

    screenings = [i for i in bioroy_se._parse_program_list(pl) if not isinstance(i, Film)]

    assert next(s for s in screenings if s.title == "Nosferatu").version.audio.kind is AudioKind.SILENT


def test_original_languages_from_audio_language(films):
    by_title = {f.title: f for f in films}
    assert by_title["Tony"].original_languages == frozenset({Language.ENGLISH})
    assert by_title["Arkipelag"].original_languages == frozenset({Language.SWEDISH})
    assert by_title["Nosferatu"].original_languages == frozenset()
    # Swedish speech without any stated subtitles may be a dubbed track.
    assert by_title["Vår jord"].original_languages == frozenset()


def test_film_page_poster_replaces_the_cropped_still(films):
    assert next(f for f in films if f.title == "Digger").poster_url == _DIGGER_POSTER


def test_film_page_poster_url():
    assert bioroy_se._page_poster(_FILM_HTML) == _DIGGER_POSTER
    assert bioroy_se._page_poster("<html></html>") == ""
