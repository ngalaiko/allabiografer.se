"""WordPress Theater production page parsing."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from parse.parsers import wp_theatre
from store import Film
from store.version import AudioKind, Language

pytestmark = pytest.mark.usefixtures("parser_clock")

_FIXTURES = Path(__file__).parent / "fixtures" / "wp_theatre"
_SITE = {"city": "Göteborg", "name": "Capitol", "screen": "CAPITOL {}"}


@pytest.fixture(autouse=True)
def tmdb_calls(monkeypatch):
    calls: list[tuple[str, int | None]] = []
    monkeypatch.setattr(wp_theatre, "_tmdb", lambda title, runtime=None: calls.append((title, runtime)))
    return calls


def _items(name: str, html: str | None = None):
    return list(wp_theatre._parse_production(html or (_FIXTURES / name).read_text(), _SITE))


def _parse(name: str):
    return [i for i in _items(name) if not isinstance(i, Film)]


def _film(name: str) -> Film:
    return next(i for i in _items(name) if isinstance(i, Film))


def test_production_screenings(tmdb_calls):
    screenings = _parse("production-tony.html")
    assert len(screenings) == 4
    s = screenings[0]
    assert s.title == "Tony"
    assert s.date.isoformat() == "2026-09-20"
    assert s.time.strftime("%H:%M") == "17:30"
    assert s.screen == "CAPITOL 1"
    assert s.cinema_name == "Capitol"
    assert s.city == "Göteborg"
    assert s.ticket_url.startswith("https://capitolgbg.internetbokningen.com/")
    assert s.film_key == "wp_theatre:tony"


def test_film_metadata(tmdb_calls):
    film = _film("production-tony.html")
    assert film.key == "wp_theatre:tony"
    assert film.overview.startswith("En 19-årig Anthony Bourdain reser till Provincetown")
    # The body ends at the runtime line; the showtimes listing is not part of it.
    assert film.overview.endswith("TV-profilen.")
    assert film.runtime == 106
    assert film.genres == ["Drama", "Dokumentär"]
    assert film.poster_url == "https://www.capitolgbg.se/wp-content/uploads/2026/09/tony.jpg"
    assert film.url == "https://www.capitolgbg.se/produktion/tony/"


def test_series_category_is_not_a_genre(tmdb_calls):
    film = _film("production-cinemateket.html")
    assert film.genres == []
    assert film.overview == ""
    assert film.title == "Blade Runner"
    assert film.key == "wp_theatre:blade runner"


def test_runtime_is_passed_to_tmdb(tmdb_calls):
    _parse("production-tony.html")
    assert tmdb_calls == [("Tony", 106)]


def test_series_prefix_stripped_for_tmdb(tmdb_calls):
    screenings = _parse("production-cinemateket.html")
    assert tmdb_calls == [("Blade Runner", None)]
    assert screenings[0].title == "Blade Runner"


def test_series_prefix_is_removed_before_film_matching_and_storage(tmdb_calls):
    html = (
        (_FIXTURES / "production-cinemateket.html")
        .read_text()
        .replace("Cinemateket: Blade Runner", "Cinemateket: In The Mood For Love")
    )
    items = list(wp_theatre._parse_production(html, _SITE))
    film = next(i for i in items if isinstance(i, Film))
    screening = next(i for i in items if not isinstance(i, Film))

    assert tmdb_calls == [("In The Mood For Love", None)]
    assert film.key == "wp_theatre:in the mood for love"
    assert film.title == screening.title == "In The Mood For Love"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Cinemateket: Blade Runner", "Blade Runner"),
        ("Cinemateket — Blade Runner", "Blade Runner"),
        ("Unga Cinemateket: När Marnie var där (Sv. tal)", "När Marnie var där (Sv. tal)"),
        ("Cinemateket: Love: Actually", "Love: Actually"),
        ("Tony", "Tony"),
    ],
)
def test_lookup_title(text, expected):
    assert wp_theatre._lookup_title(text) == expected


def test_version_tags_move_from_title_to_screening(tmdb_calls):
    html = (_FIXTURES / "production-tony.html").read_text().replace(">Tony</h1>", ">Tony (Sv. tal)</h1>")
    items = list(wp_theatre._parse_production(html, _SITE))
    screening = next(i for i in items if not isinstance(i, Film))
    assert screening.title == "Tony"
    assert screening.version.audio.languages == frozenset({Language.SWEDISH})
    assert next(i for i in items if isinstance(i, Film)).key == "wp_theatre:tony"


def test_body_states_audio_and_subtitles():
    s = _parse("production-kokuho.html")[0]
    assert s.version.audio.languages == frozenset({Language.JAPANESE})
    assert s.version.subtitles.languages == frozenset({Language.SWEDISH})
    film = _film("production-kokuho.html")
    assert film.original_languages == frozenset({Language.JAPANESE})
    assert film.runtime == 175
    assert "Japanskt tal" not in film.overview


def test_occasional_subtitles_are_not_the_default():
    s = _parse("production-la-grazia.html")[0]
    assert s.version.audio.languages == frozenset({Language.ITALIAN})
    assert s.version.subtitles.languages == frozenset({Language.SWEDISH})
    assert _film("production-la-grazia.html").original_languages == frozenset({Language.ITALIAN})


def test_dialogue_languages_are_original_languages():
    spoken = frozenset({Language.NORWEGIAN, Language.ROMANIAN, Language.ENGLISH, Language.SWEDISH})
    assert _film("production-fjord.html").original_languages == spoken
    s = _parse("production-fjord.html")[0]
    assert s.version.audio.languages == spoken
    assert s.version.subtitles.languages == frozenset({Language.SWEDISH})


def test_event_remark_overrides_subtitles():
    s = next(s for s in _parse("production-fjord.html") if s.date.isoformat() == "2026-10-12")
    assert s.version.subtitles.languages == frozenset({Language.ENGLISH})
    assert s.raw_attributes == ("ENGLISH SUBTITLES - ENGELSK TEXT",)


@pytest.mark.parametrize(
    ("remark", "expected"),
    [
        ("HUNDBIO", ("HUNDBIO",)),
        ("SISTA VISNING", ("SISTA VISNING",)),
        ("PREMIÄR Biljetter ännu ej släppta", ("PREMIÄR",)),
        ("PREMIÄR Fler visningar tillkommer", ("PREMIÄR",)),
        ("BILJETTER ÄNNU EJ SLÄPPTA", ()),
        ("REPRIS i samband med premiären av del 2", ("REPRIS i samband med premiären av del 2",)),
    ],
)
def test_event_remarks_are_raw_attributes(remark, expected):
    html = (_FIXTURES / "production-fjord.html").read_text().replace("ENGLISH SUBTITLES - ENGELSK TEXT", remark)
    s = next(i for i in _items("", html) if not isinstance(i, Film) and i.date.isoformat() == "2026-10-12")
    assert s.raw_attributes == expected
    assert s.version.subtitles.languages == frozenset({Language.SWEDISH})


def test_screen_comes_from_ticket_salong():
    s = _parse("production-cinemateket.html")[0]
    assert s.screen == "CAPITOL 3"
    assert s.raw_attributes == ("Cinemateket",)
    tony = _parse("production-tony.html")[0]
    assert tony.screen == "CAPITOL 1"
    # The venue names the screen itself; only the remark remains.
    assert tony.raw_attributes == ("STORA BIODAGEN - Halva priset",)


_KOKUHO = (_FIXTURES / "production-kokuho.html").read_text()
_KOKUHO_NOTES = "<p>2 tim 55 min Japanskt tal, svensk text.</p>"


def _kokuho(notes: str) -> list:
    return _items("", _KOKUHO.replace(_KOKUHO_NOTES, notes))


def test_duration_mid_sentence_is_not_the_runtime():
    talk = "<p>Efter visningen blir det ett 30 min samtal med regissören.</p>"
    items = _kokuho(talk + _KOKUHO_NOTES)
    film = next(i for i in items if isinstance(i, Film))
    assert film.runtime == 175
    assert film.overview.endswith("samtal med regissören.")


@pytest.mark.parametrize(
    ("notes", "audio", "subtitles"),
    [
        ("Japanskt och engelskt tal, svensk text.", {Language.JAPANESE, Language.ENGLISH}, {Language.SWEDISH}),
        ("Svensk text. Japanskt tal.", {Language.JAPANESE}, {Language.SWEDISH}),
        ("Originalspråk: japanska.", {Language.JAPANESE}, None),
    ],
)
def test_body_language_statements(notes, audio, subtitles):
    items = _kokuho(f"<p>2 tim 55 min</p><p>{notes}</p>")
    film = next(i for i in items if isinstance(i, Film))
    s = next(i for i in items if not isinstance(i, Film))
    assert film.original_languages == frozenset(audio)
    assert s.version.audio.languages == frozenset(audio)
    assert s.version.subtitles.languages == (frozenset(subtitles) if subtitles else None)


def test_dubbed_swedish_is_not_original():
    items = _kokuho("<p>2 tim 55 min svenskt tal (dubbad)</p>")
    film = next(i for i in items if isinstance(i, Film))
    s = next(i for i in items if not isinstance(i, Film))
    assert film.original_languages == frozenset()
    assert s.version.audio.languages == frozenset({Language.SWEDISH})
    assert s.version.audio.kind is AudioKind.DUBBED


@pytest.mark.parametrize("parser_clock", ["2026-12-20T12:00:00+01:00"], indirect=True)
def test_ticket_date_wins_over_inferred_year():
    # Seen in late December, "4 oktober" would infer the next year.
    s = _kokuho(_KOKUHO_NOTES)
    assert [i.date.isoformat() for i in s if not isinstance(i, Film)] == ["2026-10-04", "2026-10-07"]


class _Session:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def get(self, url, timeout=None):
        if url not in self.pages:
            raise requests.ConnectionError(url)
        return SimpleNamespace(text=self.pages[url], raise_for_status=lambda: None)


def test_failed_production_page_skips_only_that_production(monkeypatch):
    home = """<div class="wp_theatre_event_title"><a href="https://x/produktion/a/">A</a></div>
<div class="wp_theatre_event_title"><a href="https://x/produktion/kokuho/">Kokuho</a></div>"""
    pages = {"https://x/": home, "https://x/produktion/kokuho/": _KOKUHO}
    monkeypatch.setattr(wp_theatre._films, "register", lambda film, session=None: film)
    items = list(wp_theatre._parse_site(_Session(pages), {**_SITE, "url": "https://x/"}))
    assert [i.title for i in items if isinstance(i, Film)] == ["Kokuho"]
    assert len(items) == 3
