"""Spegeln programme and parser integration."""

import json
from pathlib import Path
from unittest.mock import Mock

from parse import _available
from parse.parsers import folkets_hus_och_parker as parser
from store import Film, Screening, Venue
from store.version import Language

_FIXTURES = Path(__file__).parent / "fixtures" / "biografspegeln_se"


def test_parse(monkeypatch):
    programme = json.loads((_FIXTURES / "program.json").read_text())
    home = (
        '<script type="application/json">'
        + json.dumps({"props": {"pageProps": {"programList": programme}}})
        + "</script>"
    )
    session = Mock()
    session.get.side_effect = lambda url, **kwargs: Mock(
        text=home if url == "https://biografspegeln.se/" else (_FIXTURES / "film.html").read_text()
    )
    monkeypatch.setattr(parser._http, "session", lambda: session)
    monkeypatch.setattr(parser, "_tmdb", lambda *args, **kwargs: None)
    monkeypatch.setattr(parser._films, "register", lambda film, **kwargs: film)

    items = list(parser._parse_site(parser._SITES[1]))
    assert items[0] == Venue(name="Spegeln", city="Malmö", address="Stortorget 29")
    films = {i.title: i for i in items if isinstance(i, Film)}
    shows = [i for i in items if isinstance(i, Screening)]
    assert "Spegelns filmquiz" not in films
    assert "Pickpocket" in films
    assert all(s.film_key in {f.key for f in films.values()} for s in shows)
    assert all(s.cinema_name == "Spegeln" and s.city == "Malmö" for s in shows)
    hair = next(s for s in shows if s.title == "Hair")
    assert hair.film_key == "biografspegeln_se:hair"
    assert hair.date.isoformat() == "2027-01-29"
    assert hair.time.isoformat() == "20:45:00"
    assert hair.ticket_url == "https://secure.tickster.com/ccpj820pxu4jxdk"
    assert hair.screen == "Alcazar"
    assert hair.version.audio.languages == frozenset({Language.ENGLISH})
    assert hair.version.subtitles.languages == frozenset({Language.ENGLISH})
    assert "Sing Along" in hair.raw_attributes
    grease = next(s for s in shows if s.title == "Grease")
    assert grease.version.subtitles.languages == frozenset()
    assert films["Hair"].runtime == 121
    assert films["Hair"].genres == ["Musikal"]
    assert films["Digger"].poster_url == (
        "https://biografspegeln.se/media/0qydhymd/digger_aff1.jpg?width=500&height=750&rmode=max&format=jpg"
    )
    assert not any("filmquiz" in call.args[0] for call in session.get.call_args_list)


def test_poster_fallback():
    programme = json.loads((_FIXTURES / "program.json").read_text())
    film = parser._film(programme["features"][0], site=parser._SITES[1])
    assert film.poster_url.startswith("https://biografspegeln.se/media/")
    assert "width=500&height=750" in film.poster_url


def test_discovery():
    assert "folkets_hus_och_parker" in _available()
    assert "bioroy_se" not in _available()
