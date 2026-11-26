"""Replay Cinemascenen's programme and whatever detail pages were captured."""

from datetime import datetime
from urllib.parse import urlsplit

from parse.parsers.cinemascenen_se import _SITES, _details, _showtimes

from .._shared import STOCKHOLM, catalogue_main, movie_fields, stable_key


def movie_url(url, slug):
    # The ?city= link filters showtimes on the same film page.
    parts = urlsplit(url)
    return parts._replace(query="").geturl() if parts.query == f"city={slug}" else url


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
                if film.url and detail.is_file():
                    film = _details(detail.read_text(encoding="utf-8"), film)
                    based_on = detail.name
                else:
                    based_on = path.name
                fields = movie_fields(film.title, url, film.overview, film.runtime, {"director": film.directors})
                if film.poster_url:
                    fields["image"] = film.poster_url
                if film.age_rating:
                    fields["contentRating"] = str(film.age_rating)
                movies[movie_id] = based_on, fields
            based_on, fields = movies[movie_id]
            yield (
                (f"cinemascenen-{slug}", show.cinema_name, address, city),
                show_id,
                start,
                show.ticket_url,
                show.version.audio.languages,
                show.version.subtitles.languages,
                movie_id,
                based_on,
                fields,
            )


if __name__ == "__main__":
    catalogue_main("cinemascenen_se", rows)
