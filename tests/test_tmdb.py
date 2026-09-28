"""TMDB lookups served from the stored index."""

from parse import tmdb
from store import Movie, read_movie, title_key, tmdb_index_set, write_movie


def test_cached_movie_rating_is_normalised(tmp_path):
    db = tmp_path / "test.db"
    write_movie(Movie.from_dict({"tmdb_id": 42, "title_sv": "Filmen", "age_rating": "15"}), path=db)
    tmdb_index_set(f"{title_key('Filmen')}||", 42, path=db)

    assert tmdb.lookup("Filmen", path=db) == 42
    assert read_movie(42, path=db).age_rating == "Från 15 år"
