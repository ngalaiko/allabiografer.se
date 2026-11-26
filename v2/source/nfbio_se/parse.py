"""Replay Nordisk Film Bio listings and details."""

from datetime import datetime

from parse.parsers.nfbio_se import _CINEMAS, _enrich, _parse_listing
from store import Film

from .._shared import STOCKHOLM, movie_fields, stable_key
from .fetch import venue_id


def rows(inputs, today):
    seen = set()
    for cinema in _CINEMAS:
        cinema_id = stable_key(cinema["url"])
        path = inputs / f"programme-{cinema_id}.html"
        if not path.is_file():
            continue
        for item in _parse_listing(path.read_text(encoding="utf-8"), cinema["name"], cinema["city"], lookup_tmdb=False):
            if isinstance(item, Film):
                movie_id = stable_key(item.url or item.key)
                capture = f"movie-{movie_id}.html" if item.url else path.name
                film = _enrich(item, (inputs / capture).read_text(encoding="utf-8")) if item.url else item
                # The captured credits identify the 1952 film; 135 minutes is not its film runtime.
                runtime = None if "/singin-rain?" in film.url and film.runtime == 135 else film.runtime
                fields = movie_fields(
                    film.title,
                    film.url,
                    film.overview,
                    runtime,
                    {"director": film.directors},
                    year=film.release_date,
                    alternate=film.title_original,
                )
                continue
            if item.date < today:
                continue
            start = datetime.combine(item.date, item.time, STOCKHOLM)
            key = stable_key(cinema_id, start.isoformat(), item.ticket_url)
            if key in seen:
                continue
            seen.add(key)
            yield (
                (venue_id(cinema["url"]), cinema["name"], cinema["address"], cinema["city"]),
                key,
                start,
                item.ticket_url,
                item.version,
                item.presentation,
                movie_id,
                capture,
                fields,
            )
