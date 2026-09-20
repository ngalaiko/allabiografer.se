"""nfbio.se listing page parsing."""

from pathlib import Path

import pytest

from parse.parsers import nfbio_se
from store import Film

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
    assert film.age_rating == "11-årsgräns"
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
    assert film.age_rating == "11-årsgräns"
    # The film page's poster is larger than the listing's.
    assert "styles/movie_poster/" in film.poster_url


def test_version_splits_into_format_language_subtitles(screenings):
    s = next(s for s in screenings if s.title == "Tony")
    assert s.format == "2D"
    assert s.language == "Eng."
    assert s.subtitles == "Sv."


def test_extra_version_labels_kept_in_format(screenings):
    s = next(s for s in screenings if s.date.isoformat() == "2026-09-20")
    assert s.format == "2D, Biodagen"
    s4dx = next(s for s in screenings if "4DX" in s.format)
    assert s4dx.format == "4DX 3D"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Speltid: 1 timme 46 min", 106),
        ("Speltid: 2 timmar", 120),
        ("Speltid: 34 min", 34),
        ("Speltid:", None),
    ],
)
def test_parse_duration(text, expected):
    assert nfbio_se._parse_duration(text) == expected


def test_bare_language_code_is_a_language():
    assert nfbio_se._parse_version("2D, ES, (Sv.text)") == ("2D", "ES", "Sv.")
