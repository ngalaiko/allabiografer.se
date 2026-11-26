"""Replay free, non-Tickster film screenings from saved calendar responses."""

import json

from allabiografer.sources.kraftenifinspang_se.site import _showtimes

from .._shared import facts, movie_fields, stable_key


def rows(inputs, today):
    page = 1
    seen = set()
    while True:
        capture = f"events-{page:03d}.json"
        data = json.loads((inputs / capture).read_bytes())
        for venue, film, start, fmt, audio, subtitles in _showtimes(data["events"], today):
            cinema = f"finspang-{stable_key(venue.city, venue.name)}"
            show = stable_key(cinema, film.key, start.isoformat())
            if not film.title or show in seen:
                continue
            seen.add(show)
            yield (
                (cinema, venue.name, venue.address, venue.city),
                show,
                start,
                film.url,
                *facts(format=fmt, language=audio, subtitles=subtitles),
                stable_key(film.key),
                capture,
                movie_fields(film.title, film.url, film.overview, None),
            )
        if page >= data["total_pages"]:
            return
        page += 1
