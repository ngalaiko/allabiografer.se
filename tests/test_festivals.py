"""Festival imports and static pages."""

from datetime import date
from pathlib import Path

import pytest

import build
from build.festivals import build_festivals, prepare
from parse.festivals import prisma_screenings, stockholm_screenings
from store import Festival, FestivalScreening, write_festival


@pytest.fixture
def festival():
    return {
        "slug": "test-festival",
        "year": 2026,
        "name": "Testfestival",
        "city": "Stockholm",
        "start": "2026-11-11",
        "end": "2026-11-22",
        "url": "https://example.com/",
        "screenings": [
            {
                "id": "one",
                "film_id": "film",
                "title": "Film <ett>",
                "venue": "Bio",
                "start": "2026-11-11T17:30:00+01:00",
                "end": "2026-11-11T19:30:00+01:00",
                "url": "https://example.com/tickets",
            }
        ],
    }


def test_festival_build_keeps_full_programme_before_and_after_festival(tmp_path, festival):
    db = tmp_path / "db.sqlite"
    screenings = [FestivalScreening(**s) for s in festival.pop("screenings")]
    write_festival(Festival(**festival, source="stockholm"), screenings, path=db)
    for today in (date(2026, 1, 1), date(2027, 1, 1)):
        sd = build.SiteData(out_dir=tmp_path / str(today.year), today=today)
        build_festivals(build._make_env(), sd, build._register, db)
        html = (sd.out_dir / "festival/test-festival/2026/index.html").read_text()
        assert "Film &lt;ett&gt;" in html
        assert "2026-11-22" in html
        assert "https://example.com/tickets" in html
        assert "festival-data" in html
        assert "https://allabiografer.se/festival/test-festival/2026/" in sd.sitemap_urls
        assert "/festival/test-festival/2026/" in (sd.out_dir / "festival/index.html").read_text()


def test_overlapping_screenings_have_separate_lanes(festival):
    festival["screenings"].append({**festival["screenings"][0], "id": "two"})
    result = prepare(festival)
    assert [s["lane"] for s in result["screenings"]] == [0, 1]
    assert result["films"][0]["cinemas"][0]["height"] == 92


@pytest.mark.parametrize(
    "change",
    [
        {"start": "2026-11-11T17:30:00"},
        {"end": "2026-11-11T16:30:00+01:00"},
        {"start": "2026-10-11T17:30:00+01:00"},
        {"url": "javascript:alert(1)"},
    ],
)
def test_invalid_screening_rejected(festival, change):
    festival["screenings"][0].update(change)
    with pytest.raises(ValueError, match=r"Invalid|outside festival"):
        prepare(festival)


def test_unknown_duration_is_not_invented(festival):
    festival["screenings"][0]["end"] = None
    assert prepare(festival)["screenings"][0]["duration"] is None


def test_festival_film_metadata_is_shared_between_screenings(festival):
    festival["screenings"].append(
        {
            **festival["screenings"][0],
            "id": "two",
            "runtime": 120,
            "genres": "Drama",
            "sections": "ICONS",
            "description": "En berättelse.",
            "poster_url": "https://example.com/poster.jpg",
        }
    )
    film = prepare(festival)["films"][0]
    assert film["runtime"] == 120
    assert film["genres"] == "Drama"
    assert film["sections"] == "ICONS"
    assert film["description"] == "En berättelse."
    assert film["poster_url"] == "https://example.com/poster.jpg"


def test_stockholm_import_filters_events_and_uses_local_time():
    def attr(code, value):
        return {"attribute_metadata": {"code": code}, "entered_attribute_value": {"value": value}}

    def product(identifier, when, section="ICONS"):
        return {
            "uid": identifier,
            "name": "Opening",
            "parent_url_key": "film",
            "url_key": "screening",
            "url_suffix": "",
            "custom_attributes": [
                attr("event_start_iso", when),
                attr("event_location", "Skandia"),
                attr("length", "120"),
                attr("filmtitle", "The film"),
                attr("sektion", section),
            ],
        }

    products = [
        product("yes", "2026-11-11 23:30:00"),
        product("old", "2025-11-11 17:30:00"),
        product("other", "2026-11-11 17:30:00", ""),
        {
            "url_key": "film",
            "name": "The film",
            "image": {"url": "https://example.com/poster.jpg"},
            "description": {"html": "<style>.bad {}</style><p>A &amp; B</p><script>bad()</script>"},
            "short_description": {"html": "<p>Introduction</p>"},
            "custom_attributes": [attr("genre", "Drama"), attr("director", "Director")],
        },
    ]
    result = stockholm_screenings(products, date(2026, 11, 11), date(2026, 11, 22))
    assert len(result) == 1
    assert result[0].start == "2026-11-11T23:30:00+01:00"
    assert result[0].end == "2026-11-12T01:30:00+01:00"
    assert result[0].title == "The film"
    assert result[0].url == "https://www.stockholmfilmfestival.se/screening"
    assert result[0].description == "A & B"
    assert result[0].intro == "Introduction"
    assert result[0].poster_url == "https://example.com/poster.jpg"
    assert result[0].film_url == "https://www.stockholmfilmfestival.se/film"
    assert result[0].genres == "Drama"
    assert result[0].runtime == 120


def test_prisma_import_keeps_films_and_packages_in_local_time():
    def document(identifier, kind, when="2026-10-24T12:00:00Z", key="film-key"):
        return {
            "id": identifier,
            "type": kind,
            "eventKey": key,
            "uniqueTitle": "the-film",
            "title": "The film",
            "location": "Göta 1",
            "length": 80,
            "timeStart": when,
            "timeEnd": "2026-10-24T13:20:00Z",
            "imageUrl": {"poster": None, "thumbnail": "https://example.com/thumb.jpg"},
        }

    documents = [
        document(1, "Movie"),
        document(2, "Happening"),
        document(3, "Movie", "2026-11-24T12:00:00Z"),
        document(4, "Package", key="package-key"),
    ]
    details = {
        "film-key": {
            "description": "**Lead *text*.**\n\nRest <i>of</i> it.<br />End.",
            "category": "Fiction",
            "originCountry": ["united states"],
            "language": '["english"]',
            "releaseYear": "2026",
            "crew": [{"crewType": "director", "firstname": "A", "surname": "B"}, {"crewType": "editor"}],
        }
    }
    result = prisma_screenings(documents, details, date(2026, 10, 23), date(2026, 10, 31))
    assert [s.id for s in result] == ["1", "4"]
    film, package = result
    assert film.start == "2026-10-24T14:00:00+02:00"
    assert film.end == "2026-10-24T15:20:00+02:00"
    assert film.url == "https://program.goteborgfilmfestival.se/program/the-film"
    assert film.intro == "Lead text."
    assert film.description == "Rest of it. End."
    assert film.genres == "Spelfilm"
    assert film.director == "A B"
    assert film.country == "United States"
    assert film.language == "English"
    assert film.poster_url == "https://example.com/thumb.jpg"
    assert package.url == "https://program.goteborgfilmfestival.se/paket/package-key"
    assert package.sections == "Kortfilmer"


def test_festival_stylesheet_braces_balance():
    depth = 0
    for char in Path("static/i/festival.css").read_text():
        depth += {"{": 1, "}": -1}.get(char, 0)
        assert depth >= 0
    assert depth == 0
