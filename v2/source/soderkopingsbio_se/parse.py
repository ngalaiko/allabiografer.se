"""Build Söderköpings Bio's catalogue from the saved schedule and bookings."""

import json
from datetime import datetime

from parse.parsers import _biosverige_api
from parse.parsers.soderkopingsbio_se import _ADDRESS, _CINEMA, _CITY, _MOVIE_PAGE, _TICKETS

from .._shared import STOCKHOLM, facts, stable_key
from ..tickster_se.pages import Pages, source_movie
from .fetch import SCHEDULE, showings

VENUE = (None, _CINEMA, _ADDRESS, _CITY)


def rows(inputs, today):
    schedule = json.loads((inputs / SCHEDULE).read_bytes())
    seen = set()
    for row, event, audio, subtitles in showings(Pages(inputs), schedule, today):
        title, day, time, screen, _, _, movie, booking, _ = row
        start = datetime.combine(day, time, STOCKHOLM)
        ticket = booking or (event.url if event else _TICKETS)
        show_id = stable_key(title, start.isoformat(), screen, ticket)
        if show_id in seen:
            continue
        seen.add(show_id)
        slug = movie.get("slug")
        url = _MOVIE_PAGE + slug if slug else ""
        fields = source_movie(title, url, _biosverige_api.film_details(movie))
        yield (
            VENUE,
            show_id,
            start,
            ticket,
            *facts(language=audio, subtitles=subtitles),
            stable_key(slug or title),
            SCHEDULE,
            fields,
        )
