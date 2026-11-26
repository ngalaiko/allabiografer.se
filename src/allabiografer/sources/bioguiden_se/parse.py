"""Replay Bioguiden programmes without network or TMDB."""

from datetime import datetime

from requests import Response

from allabiografer.model import Film, Venue
from allabiografer.sources.bioguiden_se.site import _SITES, _parse_pages

from .._shared import STOCKHOLM, movie_fields, stable_key


def rows(inputs, today):
    sites = {url: venue for url, venue in _SITES.items() if (inputs / f"programme-{stable_key(url)}.html").is_file()}

    def get(url):
        response = Response()
        response.status_code = 200
        response._content = (inputs / f"programme-{stable_key(url)}.html").read_bytes()
        return response

    films = {}
    locations = {(v.city, v.name): (url, v.address) for url, v in sites.items()}
    for item in _parse_pages(get, sites=sites):
        if isinstance(item, Film):
            films[item.key] = item
        elif not isinstance(item, Venue) and item.date >= today:
            film = films[item.film_key]
            url, address = locations[item.city, item.cinema_name]
            venue_key = stable_key(url)
            start = datetime.combine(item.date, item.time, STOCKHOLM)
            yield (
                (venue_key, item.cinema_name, address, item.city),
                stable_key(venue_key, item.film_key, start.isoformat(), item.screen),
                start,
                item.ticket_url,
                item.version,
                item.presentation,
                stable_key(film.key),
                f"programme-{venue_key}.html",
                movie_fields(film.title, film.url, film.overview, film.runtime),
            )
