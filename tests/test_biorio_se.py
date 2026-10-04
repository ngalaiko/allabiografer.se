"""biorio.se public showtimes API extraction."""

import json
from datetime import date, time
from pathlib import Path

import pytest

from parse.parsers import biorio_se
from store import Film, Screening, film_key
from store.version import AudioKind, Dimension, Language, PresentationSystem

_FIXTURES = Path(__file__).parent / "fixtures" / "biorio_se"
_SHOWTIMES = json.loads((_FIXTURES / "showtimes.json").read_text())
_MOVIES = json.loads((_FIXTURES / "movies.json").read_text())


def _get_json(session, url):
    if url.startswith(biorio_se._SHOWTIMES_URL):
        return _SHOWTIMES
    return _MOVIES[url.rsplit("/", 1)[1]]


@pytest.fixture
def items(monkeypatch):
    monkeypatch.setattr(biorio_se, "_get_json", _get_json)
    monkeypatch.setattr(biorio_se._films, "register", lambda film, session=None: film)
    monkeypatch.setattr(biorio_se, "_tmdb", lambda title: None)
    monkeypatch.setattr(biorio_se, "_tmdb_by_id", lambda tmdb_id: None)
    return list(biorio_se.parse())


@pytest.fixture
def screenings(items):
    return {s.ticket_url.rsplit("/", 1)[1]: s for s in items if isinstance(s, Screening)}


@pytest.fixture
def films(items):
    return {f.title: f for f in items if isinstance(f, Film)}


def test_members_only_shows_are_skipped(screenings):
    assert "2794" not in screenings
    assert len(screenings) == 5


def test_screening_fields(screenings):
    s = screenings["2814"]
    assert s.title == "Superhunden Charlie"
    assert (s.date, s.time) == (date(2026, 10, 4), time(13, 15))
    assert s.ticket_url == "https://www.biorio.se/sv/boka/2814"
    assert s.screen == "Salong 1"
    assert (s.cinema_name, s.city) == ("Bio Rio", "Stockholm")
    assert s.film_key == film_key("biorio_se", "Superhunden Charlie")


def test_shows_beyond_the_calendar_page_are_kept(screenings):
    assert screenings["2729"].date == date(2026, 12, 15)


def test_audio_and_subtitles_from_the_showtime(screenings):
    dubbed = screenings["2814"].version
    assert dubbed.audio.kind is AudioKind.DUBBED
    assert dubbed.audio.languages == frozenset({Language.SWEDISH})
    assert dubbed.subtitles.languages == frozenset({Language.SWEDISH})

    unsubtitled = screenings["2582"].version
    assert unsubtitled.audio.languages == frozenset({Language.ENGLISH})
    assert unsubtitled.subtitles.languages == frozenset()

    # "Ej angivet" means not stated, not unsubtitled.
    assert screenings["2836"].version.subtitles.languages is None


def test_tags_become_raw_attributes(screenings):
    assert screenings["2814"].raw_attributes == ("Family Time",)
    assert screenings["2647"].raw_attributes == ("Förhandsvisning", "Rendez-Vous")
    assert screenings["2582"].raw_attributes == ()


def test_3d_and_imax_flags_set_the_presentation():
    show = dict(_SHOWTIMES["showtimes"][0], is3D=True, isImax=True)
    s = biorio_se._screening(show, tmdb_id=None, film_key="")
    assert s.presentation.dimension is Dimension.THREE_D
    assert s.presentation.experiences == frozenset({PresentationSystem.IMAX})


def test_film_metadata(films):
    film = films["Quadrophenia"]
    assert film.url == "https://www.biorio.se/sv/filmer/quadrophenia"
    assert film.poster_url == (
        "https://www.biorio.se/_next/image"
        "?url=https%3A%2F%2Frio.ams3.digitaloceanspaces.com%2Fbiorio%2Fmovies%2Fmovies%2F5923"
        "%2Fposters%2F1780057673672-yirxwl.jpg&w=640&q=85"
    )
    assert film.overview.startswith("Året är 1965.")
    assert film.runtime == 120
    assert film.genres == ["Drama", "Musik"]
    assert film.release_date == "1979-09-14"
    assert film.original_languages == frozenset({Language.ENGLISH})


def test_a_dubbed_language_is_not_the_original(films):
    assert films["Superhunden Charlie"].original_languages == frozenset()


def test_one_film_per_publicly_shown_movie(films, screenings):
    assert len(films) == 5
    assert "Medan vi faller" not in films
    assert {s.film_key for s in screenings.values()} == {f.key for f in films.values()}


def test_a_resolvable_tmdb_id_skips_the_title_lookup(monkeypatch):
    monkeypatch.setattr(biorio_se, "_get_json", _get_json)
    monkeypatch.setattr(biorio_se._films, "register", lambda film, session=None: film)
    monkeypatch.setattr(biorio_se, "_tmdb", lambda title: -1)
    monkeypatch.setattr(biorio_se, "_tmdb_by_id", lambda tmdb_id: tmdb_id if tmdb_id == 1170608 else None)

    screenings = [i for i in biorio_se.parse() if isinstance(i, Screening)]

    assert {s.title: s.tmdb_id for s in screenings}["Dune: Part Three"] == 1170608
    assert {s.title: s.tmdb_id for s in screenings}["Quadrophenia"] == -1


@pytest.mark.parametrize(
    "title", ["Dune: Part One + Two", "Sagan om ringen-maraton (Ext. versions)", "Alien Double Feature"]
)
def test_a_multi_film_programme_takes_no_single_tmdb_id(monkeypatch, title):
    monkeypatch.setattr(biorio_se, "_tmdb", lambda title: -1)
    monkeypatch.setattr(biorio_se, "_tmdb_by_id", lambda tmdb_id: tmdb_id)

    assert biorio_se._tmdb_id({"title": title, "tmdbId": "438631"}) is None


def test_superhunden_charlie_release_date_falls_back_to_the_year(films):
    # The API's releaseDate is the Swedish premiere (2026-09-11); releaseYear is 2025.
    assert films["Superhunden Charlie"].release_date == "2025"


@pytest.mark.parametrize(
    ("release_date", "release_year", "expected"),
    [
        ("1979-09-14", 1979, "1979-09-14"),
        ("1950-11-20", 2014, "2014"),
        ("2024-09-07", None, ""),
        (None, 2014, "2014"),
    ],
)
def test_release_date_is_kept_only_when_it_agrees_with_the_year(release_date, release_year, expected):
    movie = {"title": "X", "slug": "x", "releaseDate": release_date, "releaseYear": release_year}
    assert biorio_se._film(movie).release_date == expected


def test_cancelled_shows_are_skipped(monkeypatch):
    showtimes = json.loads(json.dumps(_SHOWTIMES))
    statuses = {2814: "cancelled", 2582: "sold_out"}
    for show in showtimes["showtimes"]:
        show["status"] = statuses.get(show["id"], show["status"])
    monkeypatch.setattr(
        biorio_se,
        "_get_json",
        lambda s, url: showtimes if url.startswith(biorio_se._SHOWTIMES_URL) else _get_json(s, url),
    )
    monkeypatch.setattr(biorio_se._films, "register", lambda film, session=None: film)
    monkeypatch.setattr(biorio_se, "_tmdb", lambda title: None)
    monkeypatch.setattr(biorio_se, "_tmdb_by_id", lambda tmdb_id: None)

    items = list(biorio_se.parse())
    ids = {s.ticket_url.rsplit("/", 1)[1] for s in items if isinstance(s, Screening)}

    assert "2814" not in ids
    assert "2582" in ids
    assert "Superhunden Charlie" not in {f.title for f in items if isinstance(f, Film)}


def test_a_poster_without_a_jpeg_rendition_takes_the_original():
    movie = {"title": "X", "slug": "x", "posterPath": "https://rio.example/p.avif"}
    assert biorio_se._film(movie).poster_url == (
        "https://www.biorio.se/_next/image?url=https%3A%2F%2Frio.example%2Fp.avif&w=640&q=85"
    )


def test_seconds_in_the_time_are_accepted():
    show = dict(_SHOWTIMES["showtimes"][0], time="13:15:00")
    assert biorio_se._screening(show, tmdb_id=None, film_key="").time == time(13, 15)


@pytest.mark.parametrize(
    "broken",
    [
        {"time": None},
        {"time": "kväll"},
        {"movie": None},
        {"movie": {"title": "X"}},
        {"date": "2026-13-01"},
    ],
)
def test_a_malformed_show_is_skipped(monkeypatch, caplog, broken):
    showtimes = json.loads(json.dumps(_SHOWTIMES))
    show = next(s for s in showtimes["showtimes"] if s["id"] == 2582)
    show.update(broken)
    monkeypatch.setattr(
        biorio_se,
        "_get_json",
        lambda s, url: showtimes if url.startswith(biorio_se._SHOWTIMES_URL) else _get_json(s, url),
    )
    monkeypatch.setattr(biorio_se._films, "register", lambda film, session=None: film)
    monkeypatch.setattr(biorio_se, "_tmdb", lambda title: None)
    monkeypatch.setattr(biorio_se, "_tmdb_by_id", lambda tmdb_id: None)

    ids = {s.ticket_url.rsplit("/", 1)[1] for s in biorio_se.parse() if isinstance(s, Screening)}

    assert "2582" not in ids
    assert len(ids) == 4
    assert "2582" in caplog.text
