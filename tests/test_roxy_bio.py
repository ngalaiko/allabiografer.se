import json
from datetime import date, time

import requests

from parse.parsers.roxy_bio import parse
from store import Screening
from store.version import AudioKind, Language


def test_roxy_keeps_public_screenings_and_local_booking_identity(monkeypatch):
    show = {
        "title": "The Hunger Games: Sunrise on the Reaping",
        "show_time": "2026-11-21T23:15:00.000Z",
        "show_locked": 0,
        "show_time_id": 61091,
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
        response._content = json.dumps({"resultCode": 0, "data": rows}).encode()
        return response

    monkeypatch.setattr(requests.Session, "get", get)
    (screening,) = [item for item in parse() if isinstance(item, Screening)]
    assert (screening.date, screening.time, screening.screen) == (date(2026, 11, 22), time(0, 15), "Salong 1")
    assert screening.ticket_url == "https://boka.roxy.bio/#/book/61091"
    assert screening.runtime == 158
    assert screening.version.audio.kind is AudioKind.ORIGINAL
    assert screening.version.audio.languages == {Language.ENGLISH}
    assert screening.version.subtitles.languages == {Language.SWEDISH}
    assert screening.raw_attributes == ("Slutsålt",)
