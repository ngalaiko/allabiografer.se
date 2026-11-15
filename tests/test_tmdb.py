"""TMDB lookups served from the stored index."""

from datetime import UTC, datetime

import pytest
import requests

from parse import tmdb
from store import Movie, read_movie, title_key, tmdb_index_set, write_movie
from store.version import Language


def test_cached_movie_rating_is_normalised(tmp_path):
    db = tmp_path / "test.db"
    write_movie(
        Movie.from_dict(
            {
                "tmdb_id": 42,
                "title_sv": "Filmen",
                "age_rating": "15",
                "original_language": "sv",
                "spoken_languages": ["sv"],
                "directors": [],
            }
        ),
        path=db,
    )
    tmdb_index_set(f"{title_key('Filmen')}||", 42, path=db)

    assert tmdb.lookup("Filmen", path=db) == 42
    assert read_movie(42, path=db).age_rating == "Från 15 år"


class _Session:
    def __init__(self, payload: dict):
        self.payload = payload
        self.urls: list[str] = []

    def get(self, url, params=None, timeout=None):
        self.urls.append(url)
        payload = self.payload

        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return payload

        return _Resp()


@pytest.mark.parametrize(
    ("title", "year", "expected"),
    [
        ("My Favorite Things", None, 1239501),
        ("My Favourite Things", None, 1239501),
        ('- "My Favourite Things"', None, 1239501),
        ('- "My Favourite Things"', 2009, 72798),
    ],
)
def test_concert_title_hint_overrides_stale_cache_but_not_explicit_year(tmp_path, title, year, expected):
    db = tmp_path / "test.db"
    for identifier in (1239501, 72798):
        write_movie(
            Movie.from_dict(
                {"tmdb_id": identifier, "original_language": "en", "spoken_languages": ["en"], "directors": []}
            ),
            path=db,
        )
    full_title = "My Favorite Things: The Rodgers & Hammerstein 80th Anniversary Concert"
    tmdb_index_set(f"{title_key(full_title)}|2024|", 1239501, path=db)
    tmdb_index_set(f"{title_key(title)}||", 72798, path=db)
    tmdb_index_set(f"{title_key(title)}|2009|", 72798, path=db)
    session = _Session({})

    assert tmdb.lookup(title, year=year, path=db, session=session) == expected
    assert session.urls == []


def test_by_id_stores_details_for_a_known_id(tmp_path):
    db = tmp_path / "test.db"
    session = _Session({"id": 7, "title": "Filmen", "original_title": "The Film", "runtime": 99})

    assert tmdb.by_id(7, path=db, session=session) == 7
    assert read_movie(7, path=db).title_original == "The Film"
    assert session.urls == ["https://api.themoviedb.org/3/movie/7"]


def test_by_id_skips_the_network_for_a_stored_movie(tmp_path):
    db = tmp_path / "test.db"
    movie = {
        "tmdb_id": 7,
        "title_sv": "Filmen",
        "original_language": "sv",
        "spoken_languages": ["sv"],
        "directors": [],
    }
    write_movie(Movie.from_dict(movie), path=db)
    session = _Session({})

    assert tmdb.by_id(7, path=db, session=session) == 7
    assert session.urls == []


def test_stored_movie_without_directors_is_refetched(tmp_path):
    db = tmp_path / "test.db"
    details = {"tmdb_id": 7, "title_sv": "Filmen", "original_language": "sv", "spoken_languages": []}
    write_movie(Movie.from_dict(details), path=db)
    session = _Session(
        {
            **details,
            "credits": {
                "crew": [
                    {"job": "Director", "name": "Lana Wachowski"},
                    {"job": "Producer", "name": "Joel Silver"},
                    {"job": "Director", "name": "Lilly Wachowski"},
                ]
            },
        }
    )

    assert tmdb.by_id(7, path=db, session=session) == 7
    assert read_movie(7, path=db).directors == ["Lana Wachowski", "Lilly Wachowski"]
    cached_session = _Session({})
    assert tmdb.by_id(7, path=db, session=cached_session) == 7
    assert cached_session.urls == []


def test_fetch_stores_the_original_language(tmp_path):
    db = tmp_path / "test.db"
    session = _Session({"id": 7, "title": "Filmen", "original_language": "en"})

    tmdb.by_id(7, path=db, session=session)

    assert read_movie(7, path=db).original_language == "en"


def test_stored_movie_without_original_language_is_refetched(tmp_path):
    db = tmp_path / "test.db"
    write_movie(Movie.from_dict({"tmdb_id": 7, "title_sv": "Filmen"}), path=db)
    tmdb_index_set(f"{title_key('Filmen')}||", 7, path=db)
    session = _Session({"id": 7, "title": "Filmen", "original_language": "fr"})

    assert tmdb.lookup("Filmen", path=db, session=session) == 7
    assert read_movie(7, path=db).original_language == "fr"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("en", {Language.ENGLISH}),
        ("cn", {Language.CANTONESE}),
        ("nb", {Language.NORWEGIAN}),
        ("xx", set()),
        ("", set()),
    ],
)
def test_languages_map_iso_codes(code, expected):
    assert tmdb.languages(code) == expected


def test_fetch_stores_the_spoken_languages(tmp_path):
    db = tmp_path / "test.db"
    session = _Session(
        {
            "id": 7,
            "title": "Fjord",
            "original_language": "ro",
            "spoken_languages": [{"iso_639_1": "en"}, {"iso_639_1": "no"}],
        }
    )

    tmdb.by_id(7, path=db, session=session)

    assert read_movie(7, path=db).spoken_languages == ["en", "no"]


def test_stored_movie_without_spoken_languages_is_refetched(tmp_path):
    db = tmp_path / "test.db"
    write_movie(Movie.from_dict({"tmdb_id": 7, "title_sv": "Filmen", "original_language": "ro"}), path=db)
    tmdb_index_set(f"{title_key('Filmen')}||", 7, path=db)
    session = _Session({"id": 7, "title": "Filmen", "original_language": "ro", "spoken_languages": []})

    assert tmdb.lookup("Filmen", path=db, session=session) == 7
    assert read_movie(7, path=db).spoken_languages == []
    assert tmdb.by_id(7, path=db, session=_Session({})) == 7


@pytest.fixture
def tmdb_clock(monkeypatch):
    class November(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 15, 12, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(tmdb, "datetime", November, raising=False)


@pytest.mark.parametrize(("minutes", "expected"), [(114, None), (115, 7), (125, 7), (126, None), (None, 7)])
def test_cached_match_obeys_runtime_tolerance(tmp_path, minutes, expected):
    db = tmp_path / "test.db"
    write_movie(
        Movie.from_dict(
            {
                "tmdb_id": 7,
                "title_sv": "Filmen",
                "runtime": minutes,
                "original_language": "sv",
                "spoken_languages": ["sv"],
                "directors": [],
            }
        ),
        path=db,
    )
    tmdb_index_set("filmen||120", 7, path=db)

    assert tmdb.lookup("Filmen", runtime=120, path=db, session=_Session({"results": []})) == expected


@pytest.mark.usefixtures("tmdb_clock")
@pytest.mark.parametrize("lookup", [tmdb.lookup, tmdb.by_id])
@pytest.mark.parametrize(
    ("release", "swedish_release", "expected"),
    [
        ("2026-12-01", "", "Från 11 år"),
        ("2026-10-16", "", "Från 11 år"),
        ("2026-10-15", "", "Från 15 år"),
        ("2020-01-01", "2026-11-18", "Från 11 år"),
        ("", "", "Från 15 år"),
    ],
)
def test_recent_movie_rating_refreshes_once_per_run(tmp_path, lookup, release, swedish_release, expected):
    db = tmp_path / "test.db"
    write_movie(
        Movie.from_dict(
            {
                "tmdb_id": 7,
                "title_sv": "Filmen",
                "release_date": release,
                "release_date_se": swedish_release,
                "age_rating": "Från 15 år",
                "original_language": "sv",
                "spoken_languages": ["sv"],
                "directors": [],
            }
        ),
        path=db,
    )
    tmdb_index_set("filmen||", 7, path=db)
    details = {
        "id": 7,
        "title": "Filmen",
        "release_date": release,
        "original_language": "sv",
        "spoken_languages": [{"iso_639_1": "sv"}],
        "release_dates": {
            "results": [
                {
                    "iso_3166_1": "SE",
                    "release_dates": [{"type": 3, "certification": "11", "release_date": swedish_release}],
                }
            ]
        },
    }
    target = "Filmen" if lookup is tmdb.lookup else 7
    assert lookup(target, path=db, session=_Session(details)) == 7
    assert read_movie(7, path=db).age_rating == expected
    # Another title/runtime lookup or an explicit source ID must not refetch the same movie.
    assert tmdb.by_id(7, path=db, session=_Session({})) == 7
    assert read_movie(7, path=db).age_rating == expected


@pytest.mark.usefixtures("tmdb_clock")
@pytest.mark.parametrize("cached", [True, False])
@pytest.mark.parametrize(("old_runtime", "new_runtime", "expected"), [(120, 140, None), (140, 120, 7)])
def test_matching_uses_refreshed_runtime(tmp_path, monkeypatch, cached, old_runtime, new_runtime, expected):
    db = tmp_path / "test.db"
    write_movie(
        Movie.from_dict(
            {
                "tmdb_id": 7,
                "title_sv": "Filmen",
                "runtime": old_runtime,
                "release_date": "2026-12-01",
                "original_language": "sv",
                "spoken_languages": ["sv"],
                "directors": [],
            }
        ),
        path=db,
    )
    if cached:
        tmdb_index_set("filmen||120", 7, path=db)
    details = {
        "id": 7,
        "title": "Filmen",
        "runtime": new_runtime,
        "release_date": "2026-12-01",
        "original_language": "sv",
        "spoken_languages": [{"iso_639_1": "sv"}],
    }
    monkeypatch.setattr(
        tmdb,
        "_get",
        lambda session, url, **kwargs: {"results": [details]} if url.endswith("/search/movie") else details,
    )

    assert tmdb.lookup("Filmen", runtime=120, path=db, session=_Session({})) == expected
    assert read_movie(7, path=db).runtime == new_runtime


@pytest.mark.usefixtures("tmdb_clock")
def test_failed_refresh_keeps_stored_metadata_and_does_not_retry_for_each_showing(tmp_path):
    db = tmp_path / "test.db"
    movie = Movie.from_dict(
        {
            "tmdb_id": 7,
            "title_sv": "Filmen",
            "runtime": 120,
            "release_date": "2026-12-01",
            "age_rating": "Från 15 år",
            "original_language": "sv",
            "spoken_languages": ["sv"],
            "directors": [],
        }
    )
    write_movie(movie, path=db)
    tmdb_index_set("filmen||120", 7, path=db)

    class Unavailable(_Session):
        def get(self, *args, **kwargs):
            raise requests.ConnectionError("offline")

    assert tmdb.lookup("Filmen", runtime=120, path=db, session=Unavailable({})) == 7
    assert tmdb.by_id(7, path=db, session=_Session({})) == 7
    assert read_movie(7, path=db) == movie
