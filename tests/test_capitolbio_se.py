"""Capitol Stockholm's streamed calendar, independent of the other Capitols."""

from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from parse import _available
from parse.parsers import capitolbio_se as parser
from store import Film, Screening, Venue
from store.version import Language

_FIXTURES = Path(__file__).parent / "fixtures" / "capitolbio_se"
_DAY = (_FIXTURES / "day.html").read_text()
_FILM = (_FIXTURES / "film.html").read_text()


def _parse(monkeypatch, html=_DAY):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            # Still December 30 in UTC; programme dates must use Stockholm time.
            return datetime.fromisoformat("2026-12-30T23:30:00+00:00").astimezone(tz)

    def get(url, timeout):
        if "/filmer?datum=" in url:
            body = html if url.endswith(("2026-12-31", "2027-01-13")) else "<main></main>"
        elif "/sense-and-sensibility/4516" in url:
            body = _FILM
        else:
            raise requests.ConnectionError(url)
        return SimpleNamespace(text=body, raise_for_status=lambda: None)

    monkeypatch.setattr(parser, "datetime", Clock)
    monkeypatch.setattr(parser._http, "session", lambda: SimpleNamespace(get=get))
    monkeypatch.setattr(parser._films, "register", lambda film, **kwargs: film)
    monkeypatch.setattr(parser, "_tmdb", lambda title, **kwargs: None)
    return list(parser.parse())


def test_imports_streamed_calendar_across_year_boundary(monkeypatch):
    items = _parse(monkeypatch)
    assert "capitolbio_se" in _available()
    assert [i for i in items if isinstance(i, Venue)] == [
        Venue(name="Capitol", city="Stockholm", address="Sankt Eriksgatan 82")
    ]
    screenings = [i for i in items if isinstance(i, Screening)]
    assert len(screenings) == 26
    assert {s.date for s in screenings} == {date(2026, 12, 31), date(2027, 1, 13)}
    assert {(s.cinema_name, s.city) for s in screenings} == {("Capitol", "Stockholm")}
    first = screenings[0]
    assert (first.title, first.time, first.screen) == ("Lilla Spöket Laban busar vidare", time(11), "Salong 2")
    assert first.ticket_url == "https://www.capitolbio.se/boka/53668"
    french = screenings[1]
    assert (french.title, french.time, french.screen) == ("De Gaulle: Frihetens röst", time(11, 20), "Salong 3")
    assert french.version.audio.languages == frozenset({Language.FRENCH})
    assert french.version.subtitles.languages == frozenset({Language.SWEDISH})
    tea = screenings[3]
    assert tea.title == "Sense and Sensibility"
    assert tea.time == time(14)
    assert tea.version.audio.languages == frozenset({Language.ENGLISH})
    assert any("Afternoon Tea" in label for label in tea.raw_attributes)
    assert tea.film_key == "capitolbio_se:sense and sensibility"
    # A failed detail request must not remove the film's screenings.
    assert len({s.film_key for s in screenings}) == len({i.key for i in items if isinstance(i, Film)})


@pytest.mark.parametrize(
    ("label", "expected"),
    [("", None), (" | Ej textad", frozenset())],
)
def test_unknown_and_explicitly_absent_subtitles_stay_distinct(monkeypatch, label, expected):
    items = _parse(monkeypatch, _DAY.replace(" | SV text", label))
    first = next(i for i in items if isinstance(i, Screening))
    assert first.version.subtitles.languages == expected
    assert first.version.audio.languages == frozenset({Language.SWEDISH})


def test_film_details_read_runtime_and_synopsis_not_landscape_poster():
    film = parser._films.make("capitolbio_se", "Sense and Sensibility")
    detailed = parser._details(_FILM, film)
    assert detailed.runtime == 132
    assert detailed.overview.startswith("Jane Austens ikoniska Sense and Sensibility")
    assert "Visa alla detaljer" not in detailed.overview
    assert detailed.poster_url == ""


@pytest.mark.parametrize(
    ("raw", "title", "year"),
    [
        ("Smygpremiär: Arne Goes to Space med besök", "Arne Goes to Space", ""),
        ("The Hunger Games: Sunrise on the Reaping - Premiär 18 nov", "The Hunger Games: Sunrise on the Reaping", ""),
        ("Paris Is Burning (1991)", "Paris Is Burning", "1991"),
    ],
)
def test_programme_labels_do_not_become_film_titles(monkeypatch, raw, title, year):
    items = _parse(monkeypatch, _DAY.replace("De Gaulle: Frihetens röst", raw))
    film = next(i for i in items if isinstance(i, Film) and i.title == title)
    assert film.release_date == year
    assert any(i.title == title for i in items if isinstance(i, Screening))


def test_wine_tasting_is_not_a_film(monkeypatch):
    items = _parse(monkeypatch, _DAY.replace("De Gaulle: Frihetens röst", "Vinkväll med Alf &amp; Petter"))
    assert len([i for i in items if isinstance(i, Screening)]) == 24
    assert not any("Vinkväll" in i.title for i in items if isinstance(i, Film | Screening))


def test_truncated_calendar_fails_instead_of_silently_importing_part(monkeypatch):
    with pytest.raises(ValueError, match="incomplete calendar"):
        _parse(monkeypatch, _DAY + "<button>Ladda fler visningar</button>")
