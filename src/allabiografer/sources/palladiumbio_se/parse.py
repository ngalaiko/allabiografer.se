"""Replay Filmhuset Palladium's saved HTML programme and event pages."""

import re
from datetime import datetime
from functools import partial
from urllib.parse import urljoin

from allabiografer.sources.palladiumbio_se.site import (
    _ADDRESS,
    _CINEMA,
    _CITY,
    _URL,
    _hero,
    _overview,
    _poster,
    _posters,
    _showtimes,
)

from .._regional import year_from_capture
from .._shared import STOCKHOLM, facts, movie_fields, stable_key

_TRAILER = re.compile(r"youtube\.com/embed/([\w-]{11})")


def rows(inputs, today):
    page = (inputs / "programme.html").read_text(encoding="utf-8")
    showtimes = list(_showtimes(page, year_for_month=partial(year_from_capture, today)))
    posters = _posters(page)
    programme = {film.title for film, *_ in showtimes}
    seen = set()
    for film, day, time, href, screen, audio, subtitles, _ in showtimes:
        if day < today:
            continue
        start = datetime.combine(day, time, STOCKHOLM)
        ticket = urljoin(_URL, href)
        show = stable_key(film.key, screen, start.isoformat(), ticket)
        if show in seen:
            continue
        seen.add(show)
        url = urljoin(_URL, film.url) if film.url else ""
        capture = f"event-{stable_key(url)}.html" if url else "programme.html"
        detail = (inputs / capture).read_text(encoding="utf-8") if url else ""
        trailer = _TRAILER.search(detail)
        fields = movie_fields(
            film.title,
            url,
            _overview(detail),
            image=_poster(posters, film.title, programme) or _hero(detail),
            trailers=[f"https://www.youtube.com/watch?v={trailer[1]}"] if trailer else [],
        )
        yield (
            (None, _CINEMA, _ADDRESS, _CITY),
            show,
            start,
            ticket,
            *facts(language=audio, subtitles=subtitles),
            stable_key(film.key),
            capture,
            fields,
        )
