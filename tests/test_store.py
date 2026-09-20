"""Store round trips, source ownership and dedup."""

import sqlite3
from datetime import date, time

import pytest

from store import (
    Film,
    Movie,
    Screening,
    Venue,
    connect,
    film_key,
    has_poster,
    poster_key_for_film,
    poster_keys,
    poster_path,
    posters_dir,
    read_film,
    read_films,
    read_movie,
    read_movies,
    read_poster,
    read_screenings,
    read_venues,
    title_key,
    tmdb_index_get,
    tmdb_index_set,
    write_films,
    write_movie,
    write_poster,
    write_screenings,
    write_venue,
    write_venues,
)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "test.db"


def screening(**kwargs) -> Screening:
    defaults = {
        "tmdb_id": 1,
        "date": date(2026, 1, 2),
        "time": time(18, 30),
        "ticket_url": "https://example.com/1",
        "cinema_name": "Rio",
        "city": "Stockholm",
    }
    return Screening(**{**defaults, **kwargs})


# ---------------------------------------------------------------------------
# Screenings
# ---------------------------------------------------------------------------


def test_screenings_round_trip(db):
    original = screening(
        title="Film",
        source="a",
        screen="Salong 1",
        format="3D",
        language="sv",
        subtitles="en",
    )
    assert write_screenings([original], path=db, source="a") == 1
    assert read_screenings(path=db) == [original]


def test_screenings_preserve_insertion_order(db):
    rows = [screening(ticket_url=f"https://example.com/{i}") for i in range(5)]
    write_screenings(rows, path=db, source="a")
    assert [s.ticket_url for s in read_screenings(path=db)] == [s.ticket_url for s in rows]


def test_null_tmdb_id_round_trips(db):
    write_screenings([screening(tmdb_id=None, title="Okänd")], path=db, source="a")
    assert read_screenings(path=db)[0].tmdb_id is None


def test_dedup_by_key(db):
    row = screening()
    assert write_screenings([row, row], path=db, source="a") == 1
    assert len(read_screenings(path=db)) == 1


def test_dedup_ignores_format_language_subtitles(db):
    added = write_screenings(
        [screening(format="2D"), screening(format="3D")],
        path=db,
        source="a",
    )
    assert added == 1


def test_source_rewrite_replaces_own_rows_only(db):
    write_screenings([screening(ticket_url="https://a/1")], path=db, source="a")
    write_screenings([screening(cinema_name="Zita", ticket_url="https://b/1")], path=db, source="b")

    write_screenings([screening(ticket_url="https://a/2")], path=db, source="a")

    rows = read_screenings(path=db)
    assert {(s.source, s.ticket_url) for s in rows} == {
        ("a", "https://a/2"),
        ("b", "https://b/1"),
    }


def test_legacy_rows_dropped_only_for_covered_venues(db):
    # No source: legacy rows, merged in.
    write_screenings(
        [
            screening(cinema_name="Rio", ticket_url="https://legacy/rio"),
            screening(cinema_name="Zita", ticket_url="https://legacy/zita"),
        ],
        path=db,
    )
    assert {s.source for s in read_screenings(path=db)} == {""}

    write_screenings([screening(cinema_name="Rio", ticket_url="https://a/rio")], path=db, source="a")

    rows = read_screenings(path=db)
    assert {(s.source, s.ticket_url) for s in rows} == {
        ("", "https://legacy/zita"),
        ("a", "https://a/rio"),
    }


def test_legacy_rows_dropped_for_venues_listed_but_not_screened(db):
    write_screenings([screening(cinema_name="Zita", ticket_url="https://legacy/zita")], path=db)

    write_screenings(
        [],
        path=db,
        source="a",
        venues=[Venue(name="Zita", city="Stockholm")],
    )

    assert read_screenings(path=db) == []


def test_no_source_merges_without_deleting(db):
    write_screenings([screening(ticket_url="https://a/1")], path=db, source="a")
    added = write_screenings([screening(ticket_url="https://legacy/1")], path=db)
    assert added == 1
    assert len(read_screenings(path=db)) == 2


@pytest.mark.parametrize(
    "alias",
    ["Bromma", "Midsommarkransen", "Spånga"],
)
def test_city_alias_normalised(db, alias):
    write_screenings([screening(city=alias)], path=db, source="a")
    assert read_screenings(path=db)[0].city == "Stockholm"


def test_city_alias_applied_to_covered_venues(db):
    write_screenings([screening(city="Bromma", ticket_url="https://legacy/1")], path=db)
    write_screenings([screening(city="Stockholm", ticket_url="https://a/1")], path=db, source="a")
    assert [s.ticket_url for s in read_screenings(path=db)] == ["https://a/1"]


def test_read_screenings_empty_db(db):
    assert read_screenings(path=db) == []


# ---------------------------------------------------------------------------
# Movies
# ---------------------------------------------------------------------------


def movie(**kwargs) -> Movie:
    defaults = {
        "tmdb_id": 42,
        "title_sv": "Titeln",
        "title_original": "The Title",
        "overview_sv": "Handling.",
        "genres": ["Drama", "Komedi"],
        "release_date": "2026-01-01",
        "release_date_se": "2026-02-01",
        "runtime": 120,
        "poster_path": "/abc.jpg",
        "vote_average": 7.5,
        "age_rating": "11",
    }
    return Movie(**{**defaults, **kwargs})


def test_movie_round_trip(db):
    m = movie()
    write_movie(m, path=db)
    assert read_movie(42, path=db) == m


def test_movie_to_dict_inverse_of_from_dict():
    m = movie()
    assert Movie.from_dict(m.to_dict()) == m


def test_movie_nullable_fields(db):
    m = movie(tmdb_id=7, runtime=None, vote_average=None, genres=[])
    write_movie(m, path=db)
    stored = read_movie(7, path=db)
    assert stored.runtime is None
    assert stored.vote_average is None
    assert stored.genres == []


def test_movie_upsert(db):
    write_movie(movie(), path=db)
    write_movie(movie(title_sv="Ny titel"), path=db)
    assert read_movie(42, path=db).title_sv == "Ny titel"


def test_read_movie_missing(db):
    assert read_movie(999, path=db) is None


def test_read_movies(db):
    write_movie(movie(tmdb_id=1), path=db)
    write_movie(movie(tmdb_id=2), path=db)
    found = read_movies([1, 2, 3], path=db)
    assert set(found) == {1, 2}
    assert found[1].genres == ["Drama", "Komedi"]


def test_read_movies_empty(db):
    assert read_movies([], path=db) == {}


# ---------------------------------------------------------------------------
# Posters
# ---------------------------------------------------------------------------


def test_poster_write_read(db):
    write_poster(1, b"\x89PNG-bytes", "image/png", path=db)
    assert read_poster(1, path=db) == b"\x89PNG-bytes"
    assert has_poster(1, path=db)
    assert not has_poster(2, path=db)
    assert read_poster(2, path=db) is None
    assert poster_path(2, path=db) is None


def test_posters_dir_beside_db(db):
    assert posters_dir(db) == db.parent / "posters"
    write_poster(1, b"a", "image/jpeg", path=db)
    assert poster_path(1, path=db) == db.parent / "posters" / "1.jpg"


@pytest.mark.parametrize(
    ("content_type", "ext"),
    [
        ("image/jpeg", ".jpg"),
        ("image/png", ".png"),
        ("image/webp", ".webp"),
        ("image/avif", ".avif"),
        ("application/octet-stream", ".jpg"),
    ],
)
def test_poster_extension_from_content_type(db, content_type, ext):
    assert write_poster(1, b"a", content_type, path=db).suffix == ext


def test_poster_replace_leaves_one_file(db):
    write_poster(1, b"old", "image/jpeg", path=db)
    write_poster(1, b"new", "image/png", path=db)
    assert read_poster(1, path=db) == b"new"
    assert [f.name for f in posters_dir(db).iterdir()] == ["1.png"]


def test_poster_keys(db):
    write_poster(1, b"a", "image/jpeg", path=db)
    write_poster(2, b"b", "image/webp", path=db)
    write_poster(3, b"c", "image/avif", path=db)
    assert poster_keys(path=db) == {"1", "2", "3"}


def test_poster_avif_round_trip(db):
    write_poster(1, b"avif-bytes", "image/avif", path=db)
    assert poster_path(1, path=db) == posters_dir(db) / "1.avif"
    assert read_poster(1, path=db) == b"avif-bytes"


def test_poster_keys_ignores_non_images(db):
    write_poster(1, b"a", "image/jpeg", path=db)
    (posters_dir(db) / "notes.txt").write_text("x")
    assert poster_keys(path=db) == {"1"}


def test_poster_keys_without_dir(db):
    assert poster_keys(path=db) == set()


def test_poster_string_key_in_subdirectory(db):
    write_poster("bio_se/heart-of-the-beast", b"img", "image/jpeg", path=db)
    assert poster_path("bio_se/heart-of-the-beast", path=db) == posters_dir(db) / "bio_se" / "heart-of-the-beast.jpg"
    assert read_poster("bio_se/heart-of-the-beast", path=db) == b"img"
    assert has_poster("bio_se/heart-of-the-beast", path=db)


def test_poster_keys_recurse(db):
    write_poster(1, b"a", "image/jpeg", path=db)
    write_poster("bio_se/filmen", b"b", "image/png", path=db)
    assert poster_keys(path=db) == {"1", "bio_se/filmen"}


def test_poster_string_key_replace_leaves_one_file(db):
    write_poster("bio_se/filmen", b"old", "image/jpeg", path=db)
    write_poster("bio_se/filmen", b"new", "image/png", path=db)
    assert read_poster("bio_se/filmen", path=db) == b"new"
    assert [f.name for f in (posters_dir(db) / "bio_se").iterdir()] == ["filmen.png"]


# ---------------------------------------------------------------------------
# Venues
# ---------------------------------------------------------------------------


def test_venue_round_trip(db):
    v = Venue(name="Rio", city="Stockholm", address="Hornstull 1")
    write_venue(v, path=db)
    assert read_venues(path=db) == [v]


def test_venue_upsert(db):
    write_venue(Venue(name="Rio", city="Stockholm"), path=db)
    write_venue(Venue(name="Rio", city="Stockholm", address="Hornstull 1"), path=db)
    assert read_venues(path=db) == [Venue(name="Rio", city="Stockholm", address="Hornstull 1")]


def test_venue_city_normalised(db):
    write_venue(Venue(name="Rio", city="Bromma"), path=db)
    assert read_venues(path=db)[0].city == "Stockholm"


def test_write_venues_returns_count(db):
    venues = [Venue(name="Rio", city="Stockholm"), Venue(name="Zita", city="Stockholm")]
    assert write_venues(venues, path=db) == 2
    assert len(read_venues(path=db)) == 2


# ---------------------------------------------------------------------------
# TMDB index
# ---------------------------------------------------------------------------


def test_tmdb_index_get_set(db):
    assert tmdb_index_get("saknas", path=db) is None
    tmdb_index_set("film|2026|120", 42, path=db)
    assert tmdb_index_get("film|2026|120", path=db) == 42


def test_tmdb_index_overwrite(db):
    tmdb_index_set("k", 1, path=db)
    tmdb_index_set("k", 2, path=db)
    assert tmdb_index_get("k", path=db) == 2


# ---------------------------------------------------------------------------
# Films
# ---------------------------------------------------------------------------


def film(**kwargs) -> Film:
    defaults = {
        "key": "bio_se:filmen",
        "source": "bio_se",
        "title": "Filmen",
        "title_original": "The Film",
        "overview": "Handling.",
        "runtime": 95,
        "genres": ["Drama"],
        "release_date": "2026-01-01",
        "age_rating": "7",
        "poster_url": "https://bio.se/filmen.jpg",
        "url": "https://bio.se/filmen",
    }
    return Film(**{**defaults, **kwargs})


def test_film_round_trip(db):
    f = film()
    assert write_films([f], path=db) == 1
    assert read_film("bio_se:filmen", path=db) == f


def test_film_to_dict_inverse_of_from_dict():
    f = film()
    assert Film.from_dict(f.to_dict()) == f


def test_film_defaults(db):
    f = Film(key="bio_se:kort", source="bio_se", title="Kort")
    write_films([f], path=db)
    stored = read_film("bio_se:kort", path=db)
    assert stored == f
    assert stored.runtime is None
    assert stored.genres == []


def test_film_upsert(db):
    write_films([film()], path=db)
    write_films([film(overview="Ny handling.")], path=db)
    assert read_film("bio_se:filmen", path=db).overview == "Ny handling."


def test_read_film_missing(db):
    assert read_film("saknas", path=db) is None


def test_read_films(db):
    write_films([film(key="a:1"), film(key="b:2")], path=db)
    found = read_films(["a:1", "b:2", "c:3"], path=db)
    assert set(found) == {"a:1", "b:2"}
    assert found["a:1"].genres == ["Drama"]


def test_read_films_empty(db):
    assert read_films([], path=db) == {}


def test_screening_film_key_round_trip(db):
    write_screenings([screening(film_key="bio_se:filmen")], path=db, source="a")
    assert read_screenings(path=db)[0].film_key == "bio_se:filmen"


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Hjärtat", "hjärtat"),
        ("  The   Film: Part 2! ", "the film part 2"),
        ("Film²", "film2"),
    ],
)
def test_title_key(title, expected):
    assert title_key(title) == expected


def test_film_key():
    assert film_key("bio_se", "Heart of the Beast") == "bio_se:heart of the beast"


def test_poster_key_for_film():
    assert poster_key_for_film(film_key("bio_se", "Heart of the Beast")) == "bio_se/heart-of-the-beast"


def test_poster_key_for_film_truncates():
    key = poster_key_for_film(film_key("bio_se", "x " * 200))
    assert key.startswith("bio_se/")
    assert len(key.removeprefix("bio_se/")) == 100


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------

_OLD_SCHEMA = """
CREATE TABLE screenings (
  city TEXT NOT NULL, cinema TEXT NOT NULL, date TEXT NOT NULL, time TEXT NOT NULL,
  screen TEXT NOT NULL DEFAULT '', tmdb_id INTEGER, ticket_url TEXT NOT NULL,
  format TEXT NOT NULL DEFAULT '', language TEXT NOT NULL DEFAULT '', subtitles TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX screenings_key
  ON screenings (city, cinema, date, time, screen, coalesce(tmdb_id, 0), title, ticket_url, source);
"""


def test_connect_migrates_old_schema(db):
    old = sqlite3.connect(db)
    old.executescript(_OLD_SCHEMA)
    old.execute(
        "INSERT INTO screenings (city, cinema, date, time, tmdb_id, ticket_url, title, source)"
        " VALUES ('Stockholm', 'Rio', '2026-01-02', '18:30', 1, 'https://example.com/1', 'Film', 'a')"
    )
    old.commit()
    old.close()

    conn = connect(db)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(screenings)")}
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()
    assert "film_key" in columns
    assert "films" in tables

    rows = read_screenings(path=db)
    assert len(rows) == 1
    assert rows[0].film_key == ""
