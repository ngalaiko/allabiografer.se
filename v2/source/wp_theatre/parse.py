"""Replay Capitol Göteborg production pages."""

from datetime import datetime

from parse.parsers.wp_theatre import _SITES, _parse_production
from store import Film

from .._shared import STOCKHOLM, catalogue_main, movie_fields, stable_key


def rows(inputs, today):
    (site,) = _SITES
    seen = set()
    for path in sorted(inputs.glob("movie-*.html")):
        records = _parse_production(path.read_text(encoding="utf-8"), site, lookup_tmdb=False)
        film = next(records, None)
        if not isinstance(film, Film):
            continue
        fields = movie_fields(
            film.title,
            film.url,
            film.overview,
            film.runtime,
            {"director": film.directors},
            year=film.release_date,
            alternate=film.title_original,
        )
        for show in records:
            if show.date < today:
                continue
            start = datetime.combine(show.date, show.time, STOCKHOLM)
            key = stable_key(start.isoformat(), show.ticket_url)
            if key in seen:
                continue
            seen.add(key)
            yield (
                ("capitol-goteborg", site["name"], site["address"], site["city"]),
                key,
                start,
                show.ticket_url,
                show.version.audio.languages,
                show.version.subtitles.languages,
                path.stem.removeprefix("movie-"),
                path.name,
                fields,
            )


if __name__ == "__main__":
    catalogue_main("wp_theatre", rows)
