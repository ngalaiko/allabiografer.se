"""TMDB lookups served from the stored index."""

import pytest

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


def test_by_id_stores_details_for_a_known_id(tmp_path):
    db = tmp_path / "test.db"
    session = _Session({"id": 7, "title": "Filmen", "original_title": "The Film", "runtime": 99})

    assert tmdb.by_id(7, path=db, session=session) == 7
    assert read_movie(7, path=db).title_original == "The Film"
    assert session.urls == ["https://api.themoviedb.org/3/movie/7"]


def test_by_id_skips_the_network_for_a_stored_movie(tmp_path):
    db = tmp_path / "test.db"
    movie = {"tmdb_id": 7, "title_sv": "Filmen", "original_language": "sv", "spoken_languages": ["sv"]}
    write_movie(Movie.from_dict(movie), path=db)
    session = _Session({})

    assert tmdb.by_id(7, path=db, session=session) == 7
    assert session.urls == []


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
