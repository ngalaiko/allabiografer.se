"""Cross-parser post-processing in the parse CLI."""

import dataclasses
import sys
import types
from datetime import date, time

import pytest

import parse
from parse import mark_dubbed, queries, tmdb, tmdb_languages
from parse.parsers import _tmdb_cache
from store import Film, Movie, Screening, read_screenings, write_movie, write_screenings
from store.version import AudioKind, AudioVersion, ContentVersion, Language


def _screening(key: str, kind: AudioKind, *languages: Language) -> Screening:
    return Screening(
        tmdb_id=None,
        date=date(2026, 10, 4),
        time=time(18, 0),
        ticket_url="https://example.se",
        cinema_name="Bio",
        city="Stad",
        film_key=key,
        version=ContentVersion(audio=AudioVersion(kind, frozenset(languages))),
    )


def _film(key: str, *languages: Language) -> Film:
    return Film(key=key, source="s", title="t", original_languages=frozenset(languages))


def test_audio_outside_original_languages_is_dubbed():
    films = [_film("s:a", Language.ENGLISH)]
    [s] = mark_dubbed([_screening("s:a", AudioKind.UNKNOWN, Language.SWEDISH)], films)
    assert s.version.audio == AudioVersion(AudioKind.DUBBED, frozenset({Language.SWEDISH}))


def test_audio_within_original_languages_stays_unknown():
    films = [_film("s:a", Language.ENGLISH, Language.SWEDISH)]
    [s] = mark_dubbed([_screening("s:a", AudioKind.UNKNOWN, Language.SWEDISH)], films)
    assert s.version.audio.kind is AudioKind.UNKNOWN


def test_unknown_original_or_audio_languages_stay_unknown():
    films = [_film("s:a"), _film("s:b", Language.ENGLISH)]
    screenings = [
        _screening("s:a", AudioKind.UNKNOWN, Language.SWEDISH),
        _screening("s:b", AudioKind.UNKNOWN),
        _screening("s:c", AudioKind.UNKNOWN, Language.SWEDISH),
    ]
    assert [s.version.audio.kind for s in mark_dubbed(screenings, films)] == [AudioKind.UNKNOWN] * 3


def test_stated_audio_kind_is_kept():
    films = [_film("s:a", Language.ENGLISH)]
    [s] = mark_dubbed([_screening("s:a", AudioKind.SILENT, Language.SWEDISH)], films)
    assert s.version.audio.kind is AudioKind.SILENT


def test_chinese_variants_count_as_one_language():
    films = [_film("s:a", Language.CANTONESE)]
    screenings = [
        _screening("s:a", AudioKind.UNKNOWN, Language.CHINESE),
        _screening("s:a", AudioKind.UNKNOWN, Language.MANDARIN),
    ]
    assert [s.version.audio.kind for s in mark_dubbed(screenings, films)] == [AudioKind.UNKNOWN] * 2


def test_tmdb_original_language_overrides_the_site():
    films = [_film("s:a", Language.SWEDISH)]
    s = dataclasses.replace(_screening("s:a", AudioKind.UNKNOWN, Language.SWEDISH), tmdb_id=1)
    [s] = mark_dubbed([s], films, {1: frozenset({Language.ENGLISH})})
    assert s.version.audio.kind is AudioKind.DUBBED


def test_site_original_language_applies_without_tmdb_language():
    films = [_film("s:a", Language.ENGLISH)]
    s = dataclasses.replace(_screening("s:a", AudioKind.UNKNOWN, Language.SWEDISH), tmdb_id=1)
    [s] = mark_dubbed([s], films, {1: frozenset()})
    assert s.version.audio.kind is AudioKind.DUBBED


def test_tmdb_languages_read_stored_movies(tmp_path):
    db = tmp_path / "test.db"
    write_movie(Movie.from_dict({"tmdb_id": 1, "title_sv": "A", "original_language": "en"}), path=db)
    write_movie(Movie.from_dict({"tmdb_id": 2, "title_sv": "B"}), path=db)
    screenings = [dataclasses.replace(_screening("s:a", AudioKind.UNKNOWN), tmdb_id=i) for i in (1, 2, 3)]

    assert tmdb_languages(screenings, path=db) == {1: {Language.ENGLISH}, 2: set()}


def test_tmdb_languages_include_spoken_languages(tmp_path):
    db = tmp_path / "test.db"
    movie = {"tmdb_id": 1, "title_sv": "Fjord", "original_language": "ro", "spoken_languages": ["en", "no"]}
    write_movie(Movie.from_dict(movie), path=db)
    screenings = [dataclasses.replace(_screening("s:a", AudioKind.UNKNOWN), tmdb_id=1)]

    assert tmdb_languages(screenings, path=db) == {1: {Language.ROMANIAN, Language.ENGLISH, Language.NORWEGIAN}}


def _run(monkeypatch, db, items):
    module = types.SimpleNamespace(parse=lambda: iter(items))
    monkeypatch.setattr(parse.importlib, "import_module", lambda name: module)
    monkeypatch.setattr(sys, "argv", ["parse", "--output", str(db), "bio_se"])
    parse.main()


def test_empty_parse_keeps_stored_screenings(monkeypatch, tmp_path):
    db = tmp_path / "test.db"
    write_screenings([_screening("s:a", AudioKind.UNKNOWN)], path=db, source="bio_se")

    _run(monkeypatch, db, [])

    assert len(read_screenings(path=db)) == 1


@pytest.mark.usefixtures("store_clock")
def test_parse_replaces_stored_screenings(monkeypatch, tmp_path):
    db = tmp_path / "test.db"
    write_screenings([_screening("s:a", AudioKind.UNKNOWN)], path=db, source="bio_se")

    _run(monkeypatch, db, [dataclasses.replace(_screening("s:b", AudioKind.UNKNOWN), time=time(20, 0))])

    assert [s.time for s in read_screenings(path=db)] == [time(20, 0)]


def test_cli_defers_tmdb_with_exact_ordered_constraints(monkeypatch, tmp_path):
    db = tmp_path / "test.db"

    def forbidden(*args, **kwargs):
        pytest.fail("source fetching must not call TMDB")

    monkeypatch.setattr(tmdb, "lookup", forbidden)
    monkeypatch.setattr(tmdb, "by_id", forbidden)
    # A live-lookup cache hit must not override captured query constraints.
    monkeypatch.setattr(_tmdb_cache, "_cache", {("Film", 120, 2026): 123})

    def items():
        for year in (2026, 2027, 2026):
            token = _tmdb_cache.lookup("Film", runtime=120, year=year) or _tmdb_cache.lookup("Film")
            yield dataclasses.replace(_screening("s:a", AudioKind.UNKNOWN), tmdb_id=token)
        yield dataclasses.replace(_screening("s:b", AudioKind.UNKNOWN), tmdb_id=_tmdb_cache.by_id(42))
        yield dataclasses.replace(_screening("s:c", AudioKind.UNKNOWN), tmdb_id=43)

    _run(monkeypatch, db, items())

    assert queries.read_requests(path=db) == {
        "s:a": [
            {"title": "Film", "runtime": 120, "year": 2026},
            {"title": "Film", "runtime": 120, "year": 2027},
        ],
    }
    assert {s.film_key: s.tmdb_id for s in read_screenings(path=db)} == {"s:a": None, "s:b": 42, "s:c": 43}
    assert _tmdb_cache._cache == {("Film", 120, 2026): 123}


def test_cli_keeps_hints_on_empty_or_failed_fetch_and_replaces_only_own_source(monkeypatch, tmp_path):
    db = tmp_path / "test.db"
    own = {"s:old": [{"title": "Old", "runtime": 99, "year": None}]}
    other = {"other:a": [{"title": "Other", "runtime": None, "year": 2020}]}
    queries.write_requests(own, source="bio_se", path=db)
    queries.write_requests(other, source="other", path=db)

    _run(monkeypatch, db, [])
    assert queries.read_requests(path=db) == own | other

    def failed():
        yield dataclasses.replace(_screening("s:new", AudioKind.UNKNOWN), tmdb_id=_tmdb_cache.lookup("New", runtime=80))
        raise RuntimeError("incomplete fetch")

    with pytest.raises(RuntimeError, match="incomplete fetch"):
        _run(monkeypatch, db, failed())
    assert queries.read_requests(path=db) == own | other

    def success():
        yield dataclasses.replace(_screening("s:new", AudioKind.UNKNOWN), tmdb_id=_tmdb_cache.lookup("New", runtime=80))

    _run(monkeypatch, db, success())
    assert queries.read_requests(path=db) == other | {"s:new": [{"title": "New", "runtime": 80, "year": None}]}
    # A nonempty explicit-ID-only programme clears obsolete hints.
    _run(monkeypatch, db, [dataclasses.replace(_screening("s:new", AudioKind.UNKNOWN), tmdb_id=42)])
    assert queries.read_requests(path=db) == other


def test_direct_tmdb_calls_work_after_capture_exception(monkeypatch):
    monkeypatch.setattr(_tmdb_cache, "_cache", {})
    monkeypatch.setattr(tmdb, "lookup", lambda *args, **kwargs: 123)
    monkeypatch.setattr(tmdb, "by_id", lambda *args, **kwargs: 456)

    def fail():
        with _tmdb_cache.capture_requests():
            assert _tmdb_cache.lookup("Film") < 0
            assert _tmdb_cache.by_id(42) == 42
            raise RuntimeError("failed")

    with pytest.raises(RuntimeError, match="failed"):
        fail()
    assert _tmdb_cache.lookup("Film") == 123
    assert _tmdb_cache.by_id(42) == 456


def test_cli_preserves_real_parser_fallback_constraints_and_explicit_ids(monkeypatch, tmp_path):
    from parse.parsers import _biosverige_api, biorio_se, hypnostheatre_com, kiviksbio_se

    db = tmp_path / "test.db"

    def forbidden(*args, **kwargs):
        pytest.fail("source fetching must not call TMDB")

    monkeypatch.setattr(tmdb, "lookup", forbidden)
    monkeypatch.setattr(tmdb, "by_id", forbidden)
    film = Film(key="s:a", source="s", title="Film", runtime=120, release_date="2026")

    def items():
        for key, tmdb_id in [
            ("s:a", kiviksbio_se._tmdb_id(film, date(2026, 10, 4), ())),
            ("s:b", hypnostheatre_com._tmdb_id(film)),
            ("s:c", _biosverige_api.tmdb_id("Film", {"duration": 120, "originalName": "Original"})),
            ("s:d", biorio_se._tmdb_id({"title": "Film", "tmdbId": "42"})),
        ]:
            yield dataclasses.replace(
                _screening(key, AudioKind.UNKNOWN), tmdb_id=tmdb_id, ticket_url=f"https://example.se/{key}"
            )

    _run(monkeypatch, db, items())
    assert queries.read_requests(path=db) == {
        "s:a": [{"title": "Film", "runtime": 120, "year": None}],
        "s:b": [{"title": "Film", "runtime": 120, "year": 2026}],
        "s:c": [{"title": "Film", "runtime": 120, "year": None}],
    }
    assert {s.film_key: s.tmdb_id for s in read_screenings(path=db)} == {
        "s:a": None,
        "s:b": None,
        "s:c": None,
        "s:d": 42,
    }
