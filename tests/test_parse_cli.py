"""Cross-parser post-processing in the parse CLI."""

from datetime import date, time

from parse import mark_dubbed
from store import Film, Screening
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
