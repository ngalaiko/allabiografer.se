"""Replay Svenska Bio's date feed and movie metadata without network access."""

import json
from html import unescape

from parse.parsers.svenskabio_se import _CINEMAS, _dates, _showtimes

from .._shared import STOCKHOLM, movie_fields, read_page, stable_key
from .fetch import venue_id

_MOVIE_FIELDS = (
    "name",
    "description",
    "duration",
    "datePublished",
    "alternateName",
    "director",
    "actor",
    "image",
    "genre",
    "contentRating",
    "distributor",
    "trailer",
)


def movie_data(path, film):
    fields = movie_fields(film.title, film.url, "", film.runtime)
    if path.is_file():
        for script in read_page(path).select('script[type="application/ld+json"]'):
            try:
                graph = json.loads(script.get_text())["@graph"]
            except (ValueError, TypeError, KeyError):
                continue
            for node in graph:
                if node.get("@type") == "Movie" and node.get("url") == film.url:
                    fields.update((key, node[key]) for key in _MOVIE_FIELDS if node.get(key))
                    for key in ("name", "alternateName", "description"):
                        if isinstance(fields.get(key), str):
                            fields[key] = unescape(fields[key]).strip()
                    if film.url == "https://svenskabio.se/filmer/love-actually/":
                        # Svenska Bio dates this reissue; the credits identify Richard Curtis's 2003 film.
                        fields["datePublished"] = "2003"
                    return path.name, fields
    return None, fields


def rows(inputs, today):
    movies = {}
    for _, cinema_id, venue in _CINEMAS:
        first_path = inputs / f"programme-{cinema_id}-all.json"
        if not first_path.is_file():
            continue
        first = json.loads(first_path.read_bytes())
        seen = set()
        for day in _dates(first, venue):
            path = first_path if first["date"] == day else inputs / f"programme-{cinema_id}-{day}.json"
            payload = first if path == first_path else json.loads(path.read_bytes())
            for show_id, when, film, show in _showtimes(payload, day, venue, seen, lookup_tmdb=False):
                start = when.astimezone(STOCKHOLM) if when.tzinfo else when.replace(tzinfo=STOCKHOLM)
                if start.date() < today:
                    continue
                movie_id = stable_key(film.url)
                if movie_id not in movies:
                    detail, fields = movie_data(inputs / f"movie-{movie_id}.html", film)
                    movies[movie_id] = detail or path.name, fields
                based_on, fields = movies[movie_id]
                yield (
                    (venue_id(cinema_id), venue.name, venue.address, venue.city),
                    f"{cinema_id}-{show_id}",
                    start,
                    show.ticket_url,
                    show.version,
                    show.presentation,
                    movie_id,
                    based_on,
                    fields,
                )
