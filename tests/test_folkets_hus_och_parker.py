"""Folkets Hus och Parker cinema isolation."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from parse.parsers import folkets_hus_och_parker as parser
from store import Film, Screening, Venue

_FIXTURES = Path(__file__).parent / "fixtures"


def test_all_cinemas(monkeypatch):
    def fetch(url, **kwargs):
        site = next(s for s in parser._SITES if s.host in url)
        if url != f"https://{site.host}/":
            return Mock(text="<html></html>")
        data = json.loads((_FIXTURES / site.source / "program.json").read_text())
        if "props" not in data:
            data = {"props": {"pageProps": {"programList": data}}}
        return Mock(text='<script type="application/json">' + json.dumps(data) + "</script>")

    session = Mock()
    session.get.side_effect = fetch
    monkeypatch.setattr(parser._http, "session", lambda: session)
    monkeypatch.setattr(parser, "_tmdb", lambda *args, **kwargs: None)
    monkeypatch.setattr(parser._films, "register", lambda film, **kwargs: film)

    items = list(parser.parse())
    venues = [i for i in items if isinstance(i, Venue)]
    films = {i.key: i for i in items if isinstance(i, Film)}
    shows = [i for i in items if isinstance(i, Screening)]
    assert {(v.name, v.city, v.address) for v in venues} == {
        ("Bio Roy", "Göteborg", "Kungsportsavenyen 45"),
        ("Spegeln", "Malmö", "Stortorget 29"),
        ("Röda Kvarn", "Helsingborg", "Karlsgatan 7"),
    }
    assert {s.city for s in shows} == {"Göteborg", "Malmö", "Helsingborg"}
    for show in shows:
        site = next(s for s in parser._SITES if s.city == show.city)
        assert show.cinema_name == site.cinema
        film = films[show.film_key]
        assert film.source == site.source
        assert film.url.startswith(f"https://{site.host}/")
        assert not film.poster_url or film.poster_url.startswith(f"https://{site.host}/")
    ballet = next(s for s in shows if s.city == "Helsingborg" and s.title == "Nötknäpparen")
    assert ballet.date.isoformat() == "2026-12-13"
    assert ballet.time.isoformat() == "13:30:00"
    assert ballet.screen == "Stora Kvarn"
    assert ballet.ticket_url == "https://secure.tickster.com/exmu4z4dugc4gx1"
    assert "Balett" in ballet.raw_attributes


def test_site_failure_aborts_combined_snapshot(monkeypatch):
    def parse_site(site):
        if site.city == "Malmö":
            raise ValueError("missing programme")
        yield Venue(name=site.cinema, city=site.city, address=site.address)

    monkeypatch.setattr(parser, "_parse_site", parse_site)
    with pytest.raises(ValueError, match="missing programme"):
        list(parser.parse())
