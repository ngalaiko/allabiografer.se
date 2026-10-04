"""nfbio.se listing page parsing."""

from pathlib import Path

import pytest

from parse.parsers import nfbio_se
from store import Film
from store.version import Dimension, Language, PresentationSystem

_LISTING = Path(__file__).parent / "fixtures" / "nfbio_se" / "listing.html"
_FILM = Path(__file__).parent / "fixtures" / "nfbio_se" / "film.html"


@pytest.fixture(autouse=True)
def _no_tmdb(monkeypatch):
    monkeypatch.setattr(nfbio_se, "_tmdb", lambda title, runtime=None: None)


@pytest.fixture
def items():
    return list(nfbio_se._parse_listing(_LISTING.read_text(), "Nordisk Film Bio Uppsala", "Uppsala"))


@pytest.fixture
def screenings(items):
    return [i for i in items if not isinstance(i, Film)]


@pytest.fixture
def films(items):
    return [i for i in items if isinstance(i, Film)]


def test_all_showtimes_parsed(screenings):
    assert len(screenings) == 13
    assert {s.title for s in screenings} == {"Tony", "Spider-Man: Brand New Day"}


def test_dates_come_from_the_time_element(screenings):
    s = next(s for s in screenings if s.title == "Tony" and s.time.strftime("%H:%M") == "13:00")
    assert s.date.isoformat() == "2026-09-21"
    assert s.screen == "Salong 5"
    assert s.ticket_url == "https://www.nfbio.se/screening/4/ac12edf8-7633-4e98-805a-46094aceb00d"
    assert s.cinema_name == "Nordisk Film Bio Uppsala"
    assert s.city == "Uppsala"
    assert s.film_key == "nfbio_se:tony"


def test_listing_film_metadata(films):
    film = next(f for f in films if f.title == "Tony")
    assert film.key == "nfbio_se:tony"
    assert film.runtime == 106
    assert film.age_rating == "Från 11 år"
    assert film.url == "https://www.nfbio.se/tony?city=uppsala"
    assert film.poster_url == (
        "https://www.nfbio.se/sites/nfbio.se/files/styles/movie_poster_teaser/"
        "public/media-images/2026-08/tony.jpeg?itok=dYqnSmjJ"
    )


def test_unreviewed_censorship_is_not_an_age_rating(films):
    assert next(f for f in films if f.title == "Spider-Man: Brand New Day").age_rating == ""


def test_every_screening_carries_its_film_key(films, screenings):
    keys = {f.key for f in films}
    assert all(s.film_key in keys for s in screenings)


def test_film_page_fills_in_the_rest(films):
    film = nfbio_se._enrich(next(f for f in films if f.title == "Tony"), _FILM.read_text())
    assert film.overview.startswith("En 19-årig Anthony Bourdain reser till Provincetown")
    assert film.genres == ["Drama", "Komedi"]
    assert film.release_date == "2026-09-12"
    assert film.title_original == "Tony"
    assert film.age_rating == "Från 11 år"
    # The film page's JSON-LD carries the full-size original.
    assert film.poster_url == (
        "https://www.nfbio.se/sites/nfbio.se/files/media-images/2026-09/gmnt-43914a96c1-22042-vst-6aa010842cd9d.jpeg"
    )


def test_film_page_language_is_original_language(films):
    film = nfbio_se._enrich(next(f for f in films if f.title == "Tony"), _FILM.read_text())
    assert film.original_languages == frozenset({Language.ENGLISH})


def test_swedish_language_of_a_retitled_film_is_not_original():
    film = nfbio_se._films.make("nfbio_se", "Bortglömda ön")
    html = (
        _FILM.read_text()
        .replace('<div class="field__item">EN</div>', '<div class="field__item">SV</div>')
        .replace('<div class="field__item">Tony</div>', '<div class="field__item">Forgotten Island</div>')
    )
    assert nfbio_se._enrich(film, html).original_languages == frozenset()


def test_swedish_language_of_a_film_shown_in_another_language_is_not_original():
    film = nfbio_se._films.make("nfbio_se", "Tony", original_languages=frozenset({Language.ENGLISH}))
    html = _FILM.read_text().replace('<div class="field__item">EN</div>', '<div class="field__item">SV</div>')
    assert nfbio_se._enrich(film, html).original_languages == frozenset({Language.ENGLISH})


def test_swedish_language_of_a_swedish_film_is_original():
    film = nfbio_se._films.make("nfbio_se", "Tony")
    html = _FILM.read_text().replace('<div class="field__item">EN</div>', '<div class="field__item">SV</div>')
    assert nfbio_se._enrich(film, html).original_languages == frozenset({Language.SWEDISH})


def test_non_swedish_screening_audio_is_original_language(films):
    assert next(f for f in films if f.title == "Tony").original_languages == frozenset({Language.ENGLISH})


def test_placeholder_runtime_is_unknown(monkeypatch):
    calls = []
    monkeypatch.setattr(nfbio_se, "_tmdb", lambda title, runtime=None: calls.append((title, runtime)))
    html = _LISTING.read_text().replace("Speltid: 1 timme 46 min", "Speltid: 1 min")
    items = list(nfbio_se._parse_listing(html, "Nordisk Film Bio Uppsala", "Uppsala"))
    assert next(i for i in items if isinstance(i, Film) and i.title == "Tony").runtime is None
    assert ("Tony", None) in calls


def test_programme_labels_are_raw_attributes(screenings):
    s = next(s for s in screenings if s.date.isoformat() == "2026-09-20")
    assert "Biodagen" in s.raw_attributes
    assert s.raw_attributes == ("2D", "(Eng. tal)", "(Sv.text)", "Biodagen")


def test_cinema_addresses():
    assert {c["city"]: c["address"] for c in nfbio_se._CINEMAS} == {
        "Uppsala": "Marknadsgatan 1",
        "Malmö": "Per Albin Hanssons väg 38C",
    }


def test_version_splits_into_format_language_subtitles(screenings):
    s = next(s for s in screenings if s.title == "Tony")
    assert s.presentation.dimension is Dimension.TWO_D
    assert s.version.audio.languages == frozenset({Language.ENGLISH})
    assert s.version.subtitles.languages == frozenset({Language.SWEDISH})


def test_programme_labels_are_not_formats(screenings):
    s = next(s for s in screenings if s.date.isoformat() == "2026-09-20")
    assert s.presentation.experiences == frozenset()
    s4dx = next(s for s in screenings if PresentationSystem.FOUR_DX in s.presentation.experiences)
    assert s4dx.presentation.dimension is Dimension.THREE_D


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Speltid: 1 timme 46 min", 106),
        ("Speltid: 2 timmar", 120),
        ("Speltid: 34 min", 34),
        ("Speltid:", None),
        # Unreleased films carry a one-minute placeholder.
        ("Speltid: 1 min", None),
    ],
)
def test_parse_duration(text, expected):
    assert nfbio_se._parse_duration(text) == expected


def test_bare_language_code_is_a_language():
    assert nfbio_se._parse_version("2D, ES, (Sv.text)") == ("", "Spanskt tal", "Svensk text")
