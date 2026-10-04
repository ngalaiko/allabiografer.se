"""nfbio.se listing page parsing."""

from datetime import date, time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

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


_ACTORS = """<div class="field field--name-field-actors field--type-string field--label-inline">
<div class="field__label">Skådespelare</div>
<div class="field__items">
<div class="field__item">Maja Söderström</div>
<div class="field__item">Svenska röster</div>
<div class="field__item">Ebbe Skoug</div>
</div>
</div>
"""


def test_swedish_voice_cast_means_swedish_is_not_original():
    film = nfbio_se._films.make("nfbio_se", "Tony")
    html = (
        _FILM.read_text()
        .replace('<div class="field__item">EN</div>', '<div class="field__item">SV</div>')
        .replace('<div class="field field--name-field-genre', _ACTORS + '<div class="field field--name-field-genre')
    )
    assert nfbio_se._enrich(film, html).original_languages == frozenset()


def test_placeholder_genre_is_dropped(films):
    html = _FILM.read_text().replace(">Komedi<", ">Ej angivet<")
    assert nfbio_se._enrich(next(f for f in films if f.title == "Tony"), html).genres == ["Drama"]


_GENRE = '<div class="field field--name-field-genre'
_DISTRIBUTOR = """<div class="field field--name-field-copyright field--type-string field--label-inline">
<div class="field__label">Distributör</div>
<div class="field__item">Warner Bros. Entertainment</div>
</div>
"""


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        ("Dune: Part Three (Wb/Legendary)", "Dune: Part Three"),
        ("Dune: Part Three (Warner Bros.)", "Dune: Part Three"),
        ("Dune (1984)", "Dune (1984)"),
        ("(500) Days of Summer", "(500) Days of Summer"),
    ],
)
def test_original_title_drops_distributor_tag(films, original, expected):
    html = (
        _FILM.read_text()
        .replace('<div class="field__item">Tony</div>', f'<div class="field__item">{original}</div>')
        .replace(
            '<div class="field field--name-field-genre', _DISTRIBUTOR + '<div class="field field--name-field-genre'
        )
    )
    assert nfbio_se._enrich(next(f for f in films if f.title == "Tony"), html).title_original == expected


class _Session:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def get(self, url, timeout=None):
        assert "/screening/" not in url
        if url not in self.pages:
            raise requests.ConnectionError(url)
        return SimpleNamespace(text=self.pages[url], raise_for_status=lambda: None)


def test_original_languages_span_both_cinemas(monkeypatch):
    malmo = _LISTING.read_text()
    uppsala = malmo.replace("(Eng. tal)", "(Sv. tal)")
    pages = {nfbio_se._BASE + c["url"]: html for c, html in zip(nfbio_se._CINEMAS, (uppsala, malmo), strict=True)}
    monkeypatch.setattr(nfbio_se._http, "session", lambda *a: _Session(pages))
    monkeypatch.setattr(nfbio_se._films, "register", lambda film, session=None: film)

    films = [i for i in nfbio_se.parse() if isinstance(i, Film)]
    assert [f.title for f in films].count("Tony") == 1
    assert next(f for f in films if f.title == "Tony").original_languages == frozenset({Language.ENGLISH})


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("13.00", (0, time(13, 0))),
        ("9:30", (0, time(9, 30))),
        ("24.00", (1, time(0, 0))),
        ("25.15", (1, time(1, 15))),
        ("12.75", None),
        ("", None),
    ],
)
def test_parse_time(text, expected):
    assert nfbio_se._parse_time(text) == expected


def test_time_past_midnight_belongs_to_the_next_day():
    html = _LISTING.read_text().replace("13.00", "24.00", 1)
    items = list(nfbio_se._parse_listing(html, "Nordisk Film Bio Uppsala", "Uppsala"))
    s = next(
        i for i in items if not isinstance(i, Film) and i.ticket_url.endswith("ac12edf8-7633-4e98-805a-46094aceb00d")
    )
    assert (s.date, s.time) == (date(2026, 9, 22), time(0, 0))


def test_empty_listing_warns(caplog):
    assert list(nfbio_se._parse_listing("<html></html>", "Nordisk Film Bio Uppsala", "Uppsala")) == []
    assert "no films" in caplog.text
