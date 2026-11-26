"""Replay Nordisk Film Bio listings and details."""

from datetime import datetime

from allabiografer.model import Film
from allabiografer.movie_fields import film_fields
from allabiografer.sources.nfbio_se.site import _CINEMAS, _actors, _enrich, _parse_listing

from .._shared import STOCKHOLM, stable_key
from .fetch import venue_id


def rows(inputs, today):
    seen = set()
    for cinema in _CINEMAS:
        cinema_id = stable_key(cinema["url"])
        path = inputs / f"programme-{cinema_id}.html"
        if not path.is_file():
            continue
        for item in _parse_listing(path.read_text(encoding="utf-8"), cinema["name"], cinema["city"]):
            if isinstance(item, Film):
                movie_id = stable_key(item.url or item.key)
                capture = f"movie-{movie_id}.html" if item.url else path.name
                page = (inputs / capture).read_text(encoding="utf-8") if item.url else ""
                film = _enrich(item, page) if page else item
                # The captured credits identify the 1952 film; 135 minutes is not its film runtime.
                runtime = None if "/singin-rain?" in film.url and film.runtime == 135 else film.runtime
                fields = film_fields(film, runtime=runtime, credits={"actor": _actors(page) if page else []})
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
