"""Capture Osby Borgen's schedule and individual film pages."""

from parse.parsers.osbyborgen_se import _URL, _film_url, _sessions

from .._shared import capture, stable_key


def fetch_pages(session, inputs, today, *, selectors=None):
    programme = inputs / "programme.html"
    capture(session, _URL, programme)
    sessions = _sessions(programme.read_text(encoding="utf-8"))
    for film_id in dict.fromkeys(row["f_id"] for row in sessions if row.get("f_id")):
        capture(session, _film_url(film_id), inputs / f"movie-{stable_key(str(film_id))}.html")
