"""TMDB lookups served from the stored index."""

from datetime import UTC, datetime

import pytest
import requests

from parse import tmdb
from store import Film, Movie, read_movie, title_key, tmdb_index_set, write_movie
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


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        ({"runtime": 100}, 7),
        ({"runtime": 105}, 7),
        ({"runtime": 106}, None),
        ({"release_date": "2020"}, 7),
        ({"release_date": "2021", "runtime": 100}, None),
        ({"release_date": "2026-11-17", "runtime": 100}, 7),  # local premiere, not original year
        ({"overview": "Regissör: Robin Smith"}, 7),
        ({"overview": "Regissör: Taylor Jones", "runtime": 100}, None),
        ({"release_date": "2020", "runtime": 180, "overview": "Director's Cut."}, 7),
        ({"release_date": "2020", "runtime": 180}, None),
        ({}, None),  # unique title alone does not prove identity
    ],
)
def test_group_matching_checks_independent_facts_and_contradictions(tmp_path, facts, expected):
    movie = Movie.from_dict(
        {
            "tmdb_id": 7,
            "title_sv": "Reunion",
            "release_date": "2020-01-01",
            "runtime": 100,
            "directors": ["Robin Smith"],
        }
    )
    film = Film(key="a:reunion", source="a", title="Reunion", **facts)
    result = tmdb.match_group([film], {7: movie}, identifiers={7}, queries=[], path=tmp_path / "test.db")
    assert result["tmdb_id"] == expected
    assert result["reason"] == ("accepted" if expected else "unmatched")


def test_group_matching_collects_all_alias_candidates_instead_of_first_match(tmp_path):
    film = Film(key="a:reunion", source="a", title="Reunion", title_original="Homecoming", runtime=100)
    movies = {
        i: Movie.from_dict({"tmdb_id": i, "title_sv": title, "runtime": 100})
        for i, title in ((7, "Reunion"), (8, "Homecoming"))
    }
    result = tmdb.match_group([film], movies, identifiers={7}, queries=[], path=tmp_path / "test.db")
    assert result["tmdb_id"] is None
    assert result["reason"] == "ambiguous"
    assert {c["tmdb_id"] for c in result["candidates"] if not c["rejected"]} == {7, 8}


@pytest.mark.parametrize(
    ("duration", "tmdb_duration", "expected"),
    [(9, 10, 7), (95, 90, 7), (96, 90, None), (178, 170, None)],
)
def test_group_runtime_tolerance_stays_five_minutes_without_stronger_evidence(
    tmp_path, duration, tmdb_duration, expected
):
    film = Film(key="a:reunion", source="a", title="Reunion", runtime=duration)
    movie = Movie.from_dict({"tmdb_id": 7, "title_sv": "Reunion", "runtime": tmdb_duration})
    result = tmdb.match_group([film], {7: movie}, identifiers=set(), queries=[], path=tmp_path / "test.db")
    assert result["tmdb_id"] == expected


@pytest.mark.parametrize(
    ("facts", "other_directors", "expected"),
    [
        ({"overview": "Regisserad av Robin Smith.", "runtime": 110}, [], 7),
        ({"overview": "Regisserad av den visionäre filmskaparen Robin Smith.", "runtime": 110}, [], 7),
        ({"directors": ["Robin Smith"], "runtime": 110}, [], 7),
        ({"directors": ["Taylor Jones"], "overview": "Regisserad av Robin Smith.", "runtime": 110}, [], 8),
        ({"overview": "Regisserad av Robin Smith.", "runtime": 110}, ["Robin Smith"], None),
        ({"runtime": 110}, [], None),
        ({"overview": "Regisserad av Robin Smith.", "release_date": "2021-11-17"}, [], None),
        ({"overview": "Regisserad av Robin Smith.", "runtime": 110, "release_date": "2021"}, [], 8),
        ({"overview": "Regissör: Taylor Jones", "runtime": 110}, [], 8),
    ],
)
def test_group_prefers_unique_director_and_runtime_without_overriding_conflicts(
    tmp_path, facts, other_directors, expected
):
    film = Film(key="a:reunion", source="a", title="Reunion", **facts)
    movies = {
        7: Movie.from_dict(
            {
                "tmdb_id": 7,
                "title_sv": "Reunion",
                "runtime": 105,
                "release_date": "2020-01-01",
                "directors": ["Robin Smith"],
            }
        ),
        8: Movie.from_dict(
            {
                "tmdb_id": 8,
                "title_sv": "Reunion",
                "runtime": 110,
                "release_date": "2021-01-01",
                "directors": other_directors,
            }
        ),
    }
    result = tmdb.match_group([film], movies, identifiers=set(), queries=[], path=tmp_path / "test.db")
    assert result["tmdb_id"] == expected


@pytest.mark.parametrize(
    ("overview", "expected"),
    [
        ("Från Oscar- och BAFTA-belönade regissören Robin Smith kommer filmen.", 7),
        ("Ett nytt filmpaket regisserat av Robin Smith. En berättelse för barn.", 7),
        ("Robin Smith har regisserat och skrivit manus.", 7),
        ("Robin Smith har regisserat filmen.", 7),
        ("Regisserad av den visionäre filmskaparen Robin Smith är filmen en modern klassiker.", 7),
        ("Regisserad av den Oscarsbelönade filmskaparen Robin Smith.", 7),
        ("Manus av den visionäre filmskaparen Robin Smith.", None),
        ("Inte regisserad av den visionäre filmskaparen Robin Smith.", None),
        ("Regisserad av den visionäre filmskaparen Robin Smithson.", None),
        ("Robin Smith har skrivit manus. Taylor Jones har regisserat filmen.", None),
        ("Robin Smith har inte regisserat filmen.", None),
        ("Robin Smithson har regisserat filmen.", None),
        ("Robin Smith har regisserat andra filmer.", None),
        ("Inspirerad av filmer som Robin Smith har regisserat.", None),
        ("Inspirerad av regissören Robin Smiths tidigare filmer.", None),
        ("I rollerna Robin Smith och Taylor Jones.", None),
    ],
)
def test_explicit_director_phrases_not_actor_or_comparison_mentions(tmp_path, overview, expected):
    film = Film(key="a:reunion", source="a", title="Reunion", overview=overview)
    movie = Movie.from_dict({"tmdb_id": 7, "title_sv": "Reunion", "directors": ["Robin Smith"]})
    result = tmdb.match_group([film], {7: movie}, identifiers=set(), queries=[], path=tmp_path / "test.db")
    assert result["tmdb_id"] == expected


@pytest.mark.parametrize(("other", "expected"), [(["Robin Smith"], 7), (["Taylor Jones"], None)])
def test_partial_director_lists_must_agree_for_every_source(tmp_path, other, expected):
    films = [
        Film(key="a:reunion", source="a", title="Reunion", runtime=100, directors=["Robin Smith", "Taylor Jones"]),
        Film(key="b:reunion", source="b", title="Reunion", runtime=100, directors=other),
    ]
    movie = Movie.from_dict({"tmdb_id": 7, "title_sv": "Reunion", "directors": ["Robin Smith"]})
    result = tmdb.match_group(films, {7: movie}, identifiers=set(), queries=[], path=tmp_path / "test.db")
    assert result["tmdb_id"] == expected


def test_verified_director_aliases_survive_offline_without_accepting_other_crew(tmp_path, monkeypatch):
    def get(session, url, **params):
        if url.endswith("/search/movie"):
            return {"results": [{"id": 7}], "total_pages": 1}
        if url.endswith("/movie/7/credits"):
            return {
                "crew": [
                    {"job": "Director", "id": 42, "name": "Robin Smythe"},
                    {"job": "Producer", "id": 43, "name": "Taylor Jones"},
                ]
            }
        if url.endswith("/person/42"):
            return {"name": "Robin Smythe", "also_known_as": ["Robin Smith", "監督名"]}
        assert url.endswith("/movie/7")
        return {
            "id": 7,
            "title": "Reunion",
            "runtime": 100,
            "credits": {"crew": [{"job": "Director", "name": "監督名"}]},
        }

    monkeypatch.setattr(tmdb, "_get", get)
    path = tmp_path / "test.db"
    movies = {}
    film = Film(key="a:reunion", source="a", title="Reunion", runtime=100, directors=["Róbin Smíth"])
    assert tmdb.match_group([film], movies, identifiers=set(), queries=[], path=path, online=True)["tmdb_id"] == 7
    assert tmdb.match_group([film], movies, identifiers=set(), queries=[], path=path)["tmdb_id"] == 7
    producer = Film(key="a:reunion", source="a", title="Reunion", runtime=100, directors=["Taylor Jones"])
    assert tmdb.match_group([producer], movies, identifiers=set(), queries=[], path=path)["tmdb_id"] is None


@pytest.mark.parametrize(("year", "expected"), [("", None), ("1984", 8)])
@pytest.mark.parametrize("alias_field", ["alternative_titles", "translations"])
def test_online_group_matching_checks_alternative_titles_before_claiming_uniqueness(
    tmp_path, monkeypatch, year, expected, alias_field
):
    class Session(_Session):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, params=None, timeout=None):
            self.payload = (
                {"results": [{"id": 7, "title": "Reunion"}, {"id": 8, "title": "Återkomsten"}]}
                if url.endswith("/search/movie")
                else {
                    "id": int(url.rsplit("/", 1)[1]),
                    "title": "Reunion" if url.endswith("/7") else "Återkomsten",
                    "release_date": "2026-01-01" if url.endswith("/7") else "1984-01-01",
                    "runtime": 100,
                    alias_field: {"titles": [{"title": "Reunion"}]}
                    if alias_field == "alternative_titles"
                    else {"translations": [{"data": {"title": "Reunion"}}]},
                }
            )
            return super().get(url, params, timeout)

    monkeypatch.setattr(tmdb._http, "session", lambda: Session({}))
    film = Film(key="a:reunion", source="a", title="Reunion", release_date=year, runtime=100)
    result = tmdb.match_group([film], {}, identifiers=set(), queries=[], path=tmp_path / "test.db", online=True)
    assert result["tmdb_id"] == expected
    assert result["reason"] == ("accepted" if expected else "ambiguous")


@pytest.mark.parametrize(("duration", "expected"), [(125, 7), (126, None)])
def test_substantial_tmdb_plot_evidence_bounds_programme_duration_variation(tmp_path, duration, expected):
    story = (
        "A young architect returns to her childhood home with her family and discovers a hidden world "
        "behind the familiar rooms, forcing them to confront an extraordinary secret together."
    )
    film = Film(key="a:reunion", source="a", title="Reunion", runtime=duration, overview=story)
    movie = Movie.from_dict({"tmdb_id": 7, "title_sv": "Reunion", "runtime": 100, "overview_sv": story})
    assert (
        tmdb.match_group([film], {7: movie}, identifiers=set(), queries=[], path=tmp_path / "test.db")["tmdb_id"]
        == expected
    )


def test_complete_short_synopsis_does_not_override_tmdb_runtime_conflict(tmp_path):
    story = (
        "Folkkära hjältar från tre olika världar hamnar på en dödlig kollisionskurs "
        "inför ett existentiellt hot utan motstycke."
    )
    film = Film(key="a:reunion", source="a", title="Reunion", runtime=150, overview=story)
    movie = Movie.from_dict({"tmdb_id": 7, "title_sv": "Reunion", "runtime": 165, "overview_sv": story})
    result = tmdb.match_group([film], {7: movie}, identifiers=set(), queries=[], path=tmp_path / "test.db")
    assert result["tmdb_id"] is None
    assert "runtime_conflict" in result["candidates"][0]["rejected"]


@pytest.mark.parametrize(("status", "expected"), [(404, 7), (503, None)])
def test_deleted_tmdb_claim_is_rejected_but_outages_do_not_eliminate_competing_candidates(
    tmp_path, monkeypatch, status, expected
):
    path = tmp_path / "test.db"
    film = Film(key="a:reunion", source="a", title="Reunion", runtime=100)
    movies = {i: Movie.from_dict({"tmdb_id": i, "title_sv": "Reunion", "runtime": 100}) for i in (7, 8)}

    def get(session, url, **params):
        if url.endswith("/search/movie"):
            return {"results": []}
        if url.endswith("/8"):
            response = requests.Response()
            response.status_code = status
            raise requests.HTTPError(response=response)
        return {"id": 7, "title": "Reunion", "runtime": 100}

    monkeypatch.setattr(tmdb, "_get", get)
    result = tmdb.match_group([film], movies, identifiers={8}, queries=[], path=path, online=True)
    assert result["tmdb_id"] == expected
    assert tmdb.match_group([film], movies, identifiers={8}, queries=[], path=path)["tmdb_id"] == expected
    if status == 404:
        assert {c["tmdb_id"]: c["rejected"] for c in result["candidates"]}[8] == ["tmdb_not_found"]
