from dataclasses import replace
from datetime import date, datetime, time, timedelta

import pytest
import requests

from parse.parsers import bioaspen_se, biofagelbla_se
from store import Film, Screening, read_screenings, write_screenings
from store.version import Language


@pytest.fixture
def pages(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz):
            return cls(2026, 11, 18, tzinfo=tz)

    html = {}

    class Session:
        def get(self, url, timeout):
            response = requests.Response()
            response.status_code = 200 if url in html else 503
            response.encoding = "utf-8"
            response._content = html.get(url, "").encode()
            return response

    monkeypatch.setattr(bioaspen_se._http, "session", Session)
    for parser in (bioaspen_se, biofagelbla_se):
        monkeypatch.setattr(parser, "datetime", Clock)
        monkeypatch.setattr(parser, "_tmdb", lambda *args, **kwargs: None)
    return html


def test_aspen_uses_local_time_and_preserves_two_auditoriums(pages):
    base = "https://www.bioaspen.se"
    winter = "/shows/bio-aspen-wicker-1-2026-11-20t100000-0000000/"
    summer = "/shows/bio-aspen-wicker-2-2027-06-01t220000-0000000/"
    pages[f"{base}/visningar/filmer/"] = '<a class="next page-numbers" href="/page/2/">Next</a>' + (
        '<div class="movie"><a href="/movies/wicker/">Wicker</a></div>'
    )
    pages[f"{base}/page/2/"] = '<div class="movie"><a href="/movies/wicker/">Wicker</a></div>'
    pages[f"{base}/movies/wicker/"] = f"""<h1 class="entry-title">Wicker</h1>
    <a href="{winter}"><h2>11:00</h2><h3>Wicker - Barnvagnsbio</h3>
        <span class="font-menu">Salong 1</span></a>
    <a href="{summer}"><h2>00:00</h2><h3>Wicker</h3><span class="font-menu">Lusoperan</span></a>"""
    items = list(bioaspen_se.parse())
    assert [f.title for f in items if isinstance(f, Film)] == ["Wicker"]
    assert [(s.cinema_name, s.date, s.time, s.screen, s.ticket_url) for s in items if isinstance(s, Screening)] == [
        ("Aspen", date(2026, 11, 20), time(11), "Salong 1", base + winter),
        ("Aspen", date(2027, 6, 2), time(0), "Lusoperan", base + summer),
    ]
    pages.pop(f"{base}/page/2/")
    with pytest.raises(requests.HTTPError):
        list(bioaspen_se.parse())


def test_fagel_bla_uses_operator_session_id_and_subtitles(pages):
    ticket = "https://biofagelbla.se/movie/breakfast-at-tiffanys/?showtime=60383"
    pages[ticket.split("?")[0]] = '<meta name="description" content="Holly Golightly lives in New York.">'
    pages["https://biofagelbla.se/program/"] = f"""<div class="js-movie-listing-by-date">
    <article><h3>ABONNERAT FÖR SLUTET SÄLLSKAP <time datetime="2026-11-21T09:00:00+01:00">09:00</time></h3></article>
    <article><h3>Breakfast at Tiffany&rsquo;s <time datetime="2026-11-21T10:30:00+01:00">10:30</time></h3>
    <span class="leading-none">1h 55 mins</span><span class="leading-none">Text: Engelska</span>
    <a href="{ticket}">Biljetter</a></article></div>"""
    items = list(biofagelbla_se.parse())
    (screening,) = (s for s in items if isinstance(s, Screening))
    assert (screening.title, screening.date, screening.time, screening.ticket_url) == (
        "Breakfast at Tiffany\u2019s",
        date(2026, 11, 21),
        time(10, 30),
        ticket,
    )
    assert screening.version.subtitles.languages == {Language.ENGLISH}


def test_operator_replacement_keeps_history_and_other_cinemas(tmp_path):
    path = tmp_path / "schedule.db"
    today = datetime.now(bioaspen_se._TZ).date()
    row = Screening(
        title="Wicker",
        tmdb_id=None,
        date=today,
        time=time(11),
        ticket_url="https://example.org/",
        city="Stockholm",
        cinema_name="Stockholm Bio Aspen",
    )
    yesterday = replace(row, date=today - timedelta(days=1))
    other = replace(row, cinema_name="Another cinema")
    write_screenings([row, yesterday, other], path=path, source="bio_se")
    write_screenings([replace(row, cinema_name="Aspen")], path=path, source="bioguiden_se")
    direct = replace(row, cinema_name="Aspen", ticket_url="https://www.bioaspen.se/shows/wicker/")
    write_screenings([direct], path=path, source="bioaspen_se", replaces_venues=bioaspen_se.REPLACES_VENUES)
    assert set(read_screenings(path=path)) == {
        replace(yesterday, source="bio_se"),
        replace(other, source="bio_se"),
        replace(direct, source="bioaspen_se"),
    }
