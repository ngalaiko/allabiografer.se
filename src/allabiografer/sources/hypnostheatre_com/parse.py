"""Replay Hypnos Theatre's captured programme."""

from datetime import datetime

from allabiografer.sources.hypnostheatre_com.site import _ADDRESS, _CINEMA, _CITY, _showtimes

from .._shared import STOCKHOLM, movie_fields, stable_key


def rows(inputs, today):
    capture = "programme.html"
    seen = set()
    for film, show in _showtimes((inputs / capture).read_text(encoding="utf-8")):
        if show.date < today:
            continue
        start = datetime.combine(show.date, show.time, STOCKHOLM)
        movie_id = stable_key(film.key, film.release_date)
        key = stable_key(movie_id, start.isoformat(), show.ticket_url)
        if key in seen:
            continue
        seen.add(key)
        fields = movie_fields(film.title, "", film.overview, film.runtime, year=film.release_date)
        yield (
            (None, _CINEMA, _ADDRESS, _CITY),
            key,
            start,
            show.ticket_url,
            show.version,
            show.presentation,
            movie_id,
            capture,
            fields,
        )
