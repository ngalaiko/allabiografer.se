"""Replay Capitol Göteborg production pages."""

from datetime import datetime

from allabiografer.model import Film
from allabiografer.movie_fields import film_fields
from allabiografer.sources.wp_theatre.site import _SITES, _parse_production

from .._shared import STOCKHOLM, stable_key


def rows(inputs, today):
    (site,) = _SITES
    seen = set()
    for path in sorted(inputs.glob("movie-*.html")):
        records = _parse_production(path.read_text(encoding="utf-8"), site)
        film = next(records, None)
        if not isinstance(film, Film):
            continue
        fields = film_fields(film)
        for show in records:
            if show.date < today:
                continue
            start = datetime.combine(show.date, show.time, STOCKHOLM)
            key = stable_key(start.isoformat(), show.ticket_url)
            if key in seen:
                continue
            seen.add(key)
            yield (
                (None, site["name"], site["address"], site["city"]),
                key,
                start,
                show.ticket_url,
                show.version,
                show.presentation,
                path.stem.removeprefix("movie-"),
                path.name,
                fields,
                path.name,
            )
