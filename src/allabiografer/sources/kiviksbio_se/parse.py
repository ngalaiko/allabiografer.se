"""Replay Kiviks Bio's saved programme and event pages."""

from datetime import datetime
from functools import partial
from urllib.parse import urljoin

from allabiografer.sources.kiviksbio_se.site import (
    _ADDRESS,
    _CINEMA,
    _CITY,
    _URL,
    _directors,
    _overview,
    _showtimes,
    _subtitles,
)

from .._regional import year_from_capture
from .._shared import STOCKHOLM, film_id, movie_fields, stable_key


def rows(inputs, today):
    seen = set()
    page = (inputs / "programme.html").read_text(encoding="utf-8")
    for film, day, time, href, _ in _showtimes(page, year_for_month=partial(year_from_capture, today)):
        if day < today:
            continue
        start = datetime.combine(day, time, STOCKHOLM)
        url = urljoin(_URL, href)
        show = stable_key(url, start.isoformat())
        if show in seen:
            continue
        seen.add(show)
        capture = f"event-{film_id(url)}.html"
        detail = (inputs / capture).read_text(encoding="utf-8")
        fields = movie_fields(film.title, url, _overview(detail), film.runtime, {"director": _directors(detail)})
        if film.age_rating:
            fields["contentRating"] = film.age_rating
        if film.genres:
            fields["genre"] = list(film.genres)
        yield (
            (None, _CINEMA, _ADDRESS, _CITY),
            show,
            start,
            url,
            _subtitles(detail)["version"],
            _subtitles(detail)["presentation"],
            stable_key(film.key),
            capture,
            fields,
        )
