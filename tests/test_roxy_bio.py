import json
from datetime import date, time

import requests

from parse.parsers._tmdb_cache import capture_requests
from parse.parsers.riobiotomelilla_se import parse as parse_rio
from parse.parsers.roxy_bio import parse
from store import Film, Screening
from store.version import AudioKind, Language, SoundAttribute


def test_roxy_keeps_public_screenings_and_local_booking_identity(monkeypatch):
    show = {
        "title": "The Hunger Games: Sunrise on the Reaping",
        "show_time": "2026-11-21T23:15:00.000Z",
        "show_locked": 0,
        "show_time_id": 61091,
        "movie_id": 7394,
        "screen_name": "Salong 1",
        "running_time": 158,
        "movie_audio_style_name": "Original språk",
        "audio_lang": "EN",
        "subtitle_lang": "SV",
        "sold_out": 1,
    }
    rows = [show, dict(show, show_time_id=2, show_locked=1), dict(show, show_time_id=3, title="Filmquiz på Roxy!")]

    def get(session, url, *, params, timeout):
        response = requests.Response()
        response.status_code = 200
        if url.endswith("getMovieDetails"):
            data = [
                {
                    "movie_id": 7394,
                    "production_year": 2026,
                    "running_time": 160,
                }
            ]
        else:
            data = rows
        response._content = json.dumps({"resultCode": 0, "data": data}).encode()
        return response

    monkeypatch.setattr(requests.Session, "get", get)
    with capture_requests() as requests_by_token:
        items = list(parse())
    (film,) = [item for item in items if isinstance(item, Film)]
    assert film.url == "https://boka.roxy.bio/#/movie/7394"
    (screening,) = [item for item in items if isinstance(item, Screening)]
    assert (screening.date, screening.time, screening.screen) == (date(2026, 11, 22), time(0, 15), "Salong 1")
    assert screening.ticket_url == "https://boka.roxy.bio/#/book/61091"
    assert requests_by_token[screening.tmdb_id]["year"] == 2026
    assert screening.runtime == 158
    assert screening.version.audio.kind is AudioKind.ORIGINAL
    assert screening.version.audio.languages == {Language.ENGLISH}
    assert screening.version.subtitles.languages == {Language.SWEDISH}
    assert screening.raw_attributes == ()


def test_rio_imports_a_public_dubbed_booking_with_its_own_runtime(monkeypatch):
    def get(session, url, *, params, timeout):
        assert url.startswith("https://riobiotomelilla.se/")
        assert params["cinema_id"] == 8
        response = requests.Response()
        response.status_code = 200
        data = (
            [{"movie_id": 7055, "running_time": 103}]
            if url.endswith("getMovieDetails")
            else [
                {
                    "title": "Hexe: Den magiska världen",
                    "show_time": "2026-11-27T15:00:00.000Z",
                    "show_locked": 0,
                    "show_time_id": 60998,
                    "movie_id": 7055,
                    "screen_name": "Salong 1 Rio",
                    "running_time": 109,
                    "movie_audio_style_name": "Dubbad",
                    "audio_lang": "SV",
                    "subtitle_lang": "SV",
                    "movie_sound_id": 2,
                }
            ]
        )
        response._content = json.dumps({"resultCode": 0, "data": data}).encode()
        return response

    monkeypatch.setattr(requests.Session, "get", get)
    _, film, screening = parse_rio()
    assert (screening.city, screening.date, screening.time) == ("Tomelilla", date(2026, 11, 27), time(16, 0))
    assert screening.ticket_url == "https://riobiotomelilla.se/#/book/60998"
    assert film.runtime == screening.runtime == 109
    assert screening.version.audio.kind is AudioKind.DUBBED
    assert screening.presentation.sound == {SoundAttribute.SURROUND_7_1}
