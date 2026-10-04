"""BioSverige (Cinecore) schedule API extraction across cinema sites."""

import json
from datetime import date, time
from pathlib import Path
from types import SimpleNamespace

import requests

from parse.parsers import _biosverige_api, biosverige_se
from parse.parsers._biosverige_api import film_details as _film_details
from parse.parsers._biosverige_api import parse_title as _parse_title
from parse.parsers._biosverige_api import showtimes as _showtimes
from store import Film, Language, Screening, Venue, film_key

_FIXTURES = Path(__file__).parent / "fixtures" / "biosverige_se"
_SCHEDULE = json.loads((_FIXTURES / "eventschedules.json").read_text())
_CASABLANCA = (_FIXTURES / "tickster_casablanca.html").read_text()
_JARPEN = (_FIXTURES / "tickster_jarpen.html").read_text()


def test_showtimes_read_schedule_rows_with_screen_and_audio_tags():
    assert [s[:6] for s in _showtimes(_SCHEDULE)] == [
        ("Bortglömda ön", date(2026, 10, 4), time(15, 0), "Casablanca", "Svenskt tal", "Svensk text"),
        ("Resan till Piemonte", date(2026, 10, 4), time(18, 30), "Casablanca", "Svenskt tal", "Svensk text"),
        ("Resan till Piemonte", date(2026, 10, 6), time(14, 0), "Casablanca", "Svenskt tal", "Svensk text"),
        ("Kärlek över Tanger", date(2026, 10, 13), time(14, 0), "Casablanca", "", "Svensk text"),
    ]


def test_showtimes_skip_rows_without_start_or_title():
    rows = [{"eventName": "Film", "startDate": ""}, {"eventName": "", "startDate": "2026-10-04T15:00:00"}]

    assert list(_showtimes(rows)) == []


def test_showtimes_skip_deleted_rows():
    rows = [{**_SCHEDULE[0], "deleted": True}, _SCHEDULE[1]]

    assert [s[0] for s in _showtimes(rows)] == ["Resan till Piemonte"]


def test_film_details_read_the_movie_record():
    details = _film_details(_SCHEDULE[3]["movie"])

    assert details["poster_url"] == (
        "https://cdn.incode.se/content/E4046CAD-672D-4E04-829C-DFB7C472E7A7.jpg?resize=600x900"
    )
    assert details["overview"].startswith("En sensuell och hjärtevärmande feelgood")
    assert details["runtime"] == 116
    assert details["age_rating"] == "Barntillåten"
    assert details["title_original"] == "Calle Malaga"
    assert details["release_date"] == "2026-10-09"
    assert details["genres"] == []


def test_parse_title_reads_spaced_and_unspaced_tags():
    assert _parse_title("Bortglömda ön (Sv.Txt) (Sv. Tal)") == ("Bortglömda ön", "Svenskt tal", "Svensk text")
    assert _parse_title("Digger (Sv.Txt) (Eng.Tal)") == ("Digger", "Engelskt tal", "Svensk text")


def test_parse_title_drops_unknown_language_codes():
    assert _parse_title("Film (Xq.Tal)") == ("Film", "", "")


def test_sites_exclude_cinemas_other_parsers_cover():
    hosts = {site.url for site in biosverige_se._SITES}

    assert not any("soderkoping" in h for h in hosts)


def test_sites_include_smedjebacken():
    assert "https://smedjebacken.biosverige.se" in {site.url for site in biosverige_se._SITES}


class _Session:
    def __init__(self, pages: dict[str, object]):
        self.pages = pages

    def get(self, url, params=None, timeout=None):
        if url not in self.pages:
            raise requests.ConnectionError(url)
        body = self.pages[url]
        return SimpleNamespace(
            text=body if isinstance(body, str) else "",
            json=lambda: body,
            raise_for_status=lambda: None,
        )


_KARLSBORG, _FILIPSTAD, _JARPEN_SITE = (
    next(s for s in biosverige_se._SITES if s.city == city) for city in ("Karlsborg", "Filipstad", "Järpen")
)


def _parse(monkeypatch, pages: dict[str, object], tmdb=lambda title, runtime=None: None) -> list:
    monkeypatch.setattr(biosverige_se._http, "session", lambda *a: _Session(pages))
    monkeypatch.setattr(biosverige_se._films, "register", lambda film, session=None: film)
    monkeypatch.setattr(_biosverige_api, "_tmdb", tmdb)
    return list(biosverige_se.parse())


def test_parse_yields_venues_films_and_screenings(monkeypatch):
    items = _parse(monkeypatch, {_KARLSBORG.url + "/api/eventschedules": _SCHEDULE})
    venues = [i for i in items if isinstance(i, Venue)]
    films = [i for i in items if isinstance(i, Film)]
    screenings = [i for i in items if isinstance(i, Screening)]

    assert len(venues) == len(biosverige_se._SITES)
    assert [f.title for f in films] == ["Bortglömda ön", "Resan till Piemonte", "Kärlek över Tanger"]
    assert [f.key for f in films] == [film_key("biosverige_se", f.title) for f in films]
    assert films[0].url == "https://casablancabio.se/filmer/bortglomda-on-(svtxt)-(sv-tal)_1"
    assert len(screenings) == 4
    assert {s.film_key for s in screenings} == {f.key for f in films}
    assert {(s.cinema_name, s.city) for s in screenings} == {(_KARLSBORG.name, "Karlsborg")}
    assert {s.ticket_url for s in screenings} == {_KARLSBORG.tickets}


def test_parse_shares_films_across_sites_and_survives_a_failing_site(monkeypatch):
    items = _parse(
        monkeypatch,
        {_KARLSBORG.url + "/api/eventschedules": _SCHEDULE, _FILIPSTAD.url + "/api/eventschedules": _SCHEDULE[:1]},
    )
    films = [i for i in items if isinstance(i, Film)]
    screenings = [i for i in items if isinstance(i, Screening)]

    assert [f.title for f in films].count("Bortglömda ön") == 1
    assert {s.city for s in screenings} == {"Karlsborg", "Filipstad"}
    assert len(screenings) == 5


def test_parse_skips_a_site_answering_with_a_non_list(monkeypatch):
    items = _parse(
        monkeypatch,
        {
            _KARLSBORG.url + "/api/eventschedules": {"message": "error"},
            _FILIPSTAD.url + "/api/eventschedules": _SCHEDULE[:1],
        },
    )

    assert {s.city for s in items if isinstance(s, Screening)} == {"Filipstad"}


def test_parse_takes_version_tickets_and_labels_from_tickster(monkeypatch):
    items = _parse(
        monkeypatch,
        {_KARLSBORG.url + "/api/eventschedules": _SCHEDULE, _KARLSBORG.programme: _CASABLANCA},
    )
    island, evening, matinee, tanger = [i for i in items if isinstance(i, Screening)]

    # Schedule says "(Sv.Txt) (Sv. Tal)"; Tickster says "(Sv. tal)": dubbed, no subtitles.
    assert island.version.audio.languages == {Language.SWEDISH}
    assert island.version.subtitles.languages == frozenset()
    assert evening.version.subtitles.languages == {Language.SWEDISH}
    assert [s.ticket_url for s in (island, evening, matinee, tanger)] == [
        "https://www.tickster.com/se/sv/events/88wh4hm57ftc188/2026-10-04/bortglomda-on-sv-tal",
        "https://www.tickster.com/se/sv/events/njzjpg775wk39ul/2026-10-04/resan-till-piemonte-sv-txt",
        "https://www.tickster.com/se/sv/events/zdyf7uvvxdkvyn4/2026-10-06/resan-till-piemonte-dagbio-sv-txt",
        "https://www.tickster.com/se/sv/events/tlur9z975xfy6rn/2026-10-13/karlek-over-tanger-dagbio-sv-txt",
    ]
    assert [s.raw_attributes for s in (island, evening, matinee, tanger)] == [(), (), ("Dagbio",), ("Dagbio",)]


def _row(name: str, start: str) -> dict:
    return {"eventName": name, "startDate": start, "venueName": "Järpen Bion"}


def test_parse_reads_long_form_tickster_tags_and_keeps_schedule_subtitles_when_cut(monkeypatch):
    schedule = [
        _row("Bortglömda ön (Sv.Txt) (Sv. Tal)", "2026-10-11T15:00:00"),
        _row("Spa Weekend (Sv.Txt) (Eng.Tal)", "2026-10-22T19:00:00"),
        _row("Avengers: Endgame Encore (Sv.Txt) (Eng.Tal)", "2026-10-25T19:00:00"),
    ]
    items = _parse(
        monkeypatch,
        {_JARPEN_SITE.url + "/api/eventschedules": schedule, _JARPEN_SITE.programme: _JARPEN},
    )
    island, spa, avengers = [i for i in items if isinstance(i, Screening)]

    # "Bortglömda ön (Tal: Svenska (dubbat))"
    assert island.version.audio.languages == {Language.SWEDISH}
    assert island.version.subtitles.languages == frozenset()
    # "Spa Weekend STICKBIO"
    assert spa.raw_attributes == ("STICKBIO",)
    assert spa.version.subtitles.languages == {Language.SWEDISH}
    # "Avengers: Endgame Encore (Tal: Engelska) (Text: S", cut by Tickster
    assert avengers.version.audio.languages == {Language.ENGLISH}
    assert avengers.version.subtitles.languages == {Language.SWEDISH}
    assert avengers.ticket_url == (
        "https://www.tickster.com/se/sv/events/t9ugud6y70vgefy/2026-10-25/avengers-endgame-encore-tal-engelska-text-s"
    )


def test_parse_looks_up_tmdb_with_runtime_then_title_then_original_name(monkeypatch):
    calls = []
    known = {("Bortglömda ön", 109): 1, ("Resan till Piemonte", None): 2, ("Calle Malaga", 116): 3}

    def tmdb(title, runtime=None):
        calls.append((title, runtime))
        return known.get((title, runtime))

    items = _parse(monkeypatch, {_KARLSBORG.url + "/api/eventschedules": _SCHEDULE}, tmdb=tmdb)

    assert [s.tmdb_id for s in items if isinstance(s, Screening)] == [1, 2, 2, 3]
    assert ("Kärlek över Tanger", 116) in calls


def test_parse_trusts_a_long_tickster_title_that_ends_whole(monkeypatch):
    site = next(s for s in biosverige_se._SITES if s.city == "Mariannelund")
    card = (
        '<div class="c-card"><a href="/se/sv/events/z/2026-10-18/faret-shaun" class="c-card__body">'
        '<h2 class="c-card__title">Fåret Shaun och monstret på bondgården (Sv. tal)</h2></a>'
        '<span class="c-card__label">18 okt 2026, Mariannelunds Bio</span></div>'
    )
    schedule = [_row("Fåret Shaun och monstret på bondgården (Sv.Txt) (Sv.Tal)", "2026-10-18T15:00:00")]
    items = _parse(monkeypatch, {site.url + "/api/eventschedules": schedule, site.programme: card})
    (shaun,) = [i for i in items if isinstance(i, Screening)]

    assert shaun.version.subtitles.languages == frozenset()
