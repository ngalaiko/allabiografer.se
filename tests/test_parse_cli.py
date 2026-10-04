"""Cross-parser post-processing in the parse CLI."""

import dataclasses
import sys
import types
from datetime import date, time

import parse
from parse import mark_dubbed, tmdb_languages
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


def test_parse_replaces_stored_screenings(monkeypatch, tmp_path):
    db = tmp_path / "test.db"
    write_screenings([_screening("s:a", AudioKind.UNKNOWN)], path=db, source="bio_se")

    _run(monkeypatch, db, [dataclasses.replace(_screening("s:b", AudioKind.UNKNOWN), time=time(20, 0))])

    assert [s.time for s in read_screenings(path=db)] == [time(20, 0)]
