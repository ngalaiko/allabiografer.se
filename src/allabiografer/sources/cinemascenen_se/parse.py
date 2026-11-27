"""Replay Cinemascenen's programme and whatever detail pages were captured."""

from datetime import datetime
from urllib.parse import urlsplit

from allabiografer.movie_fields import film_fields
from allabiografer.sources.cinemascenen_se.site import _SITES, _actors, _details, _showtimes

from .._shared import STOCKHOLM, stable_key


def movie_url(url, slug):
    # The ?city= link filters showtimes on the same film page.
    parts = urlsplit(url)
    return parts._replace(query="").geturl() if parts.query == f"city={slug}" else url


def venue_id(slug):
    return slug


def rows(inputs, today):
    movies = {}
    seen = set()
    for slug, city, address in _SITES:
        path = inputs / f"programme-{slug}.html"
        if not path.is_file():
            continue
        for film, show in _showtimes(path.read_text(encoding="utf-8"), city):
            if show.date < today:
                continue
            url = movie_url(film.url, slug)
            movie_id = stable_key(url or film.key)
            start = datetime.combine(show.date, show.time, STOCKHOLM)
            show_id = stable_key(slug, start.isoformat(), show.screen, movie_id)
            if show_id in seen:
                continue
            seen.add(show_id)
            if movie_id not in movies:
                detail = inputs / f"movie-{movie_id}.html"
                actors = []
                if film.url and detail.is_file():
                    page = detail.read_text(encoding="utf-8")
                    film = _details(page, film)
                    actors = _actors(page)
                    based_on = detail.name
                else:
                    based_on = path.name
                fields = film_fields(film, url, credits={"actor": actors})
                movies[movie_id] = based_on, fields
            based_on, fields = movies[movie_id]
            yield (
                (venue_id(slug), show.cinema_name, address, city),
                show_id,
                start,
                show.ticket_url,
                show.version,
                show.presentation,
                movie_id,
                based_on,
                fields,
                path.name,
            )
