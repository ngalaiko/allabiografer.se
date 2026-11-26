"""Capture Cinemascenen's city programmes and linked film details."""

import logging
from collections import defaultdict

from requests import RequestException

from parse.parsers.cinemascenen_se import _SITES, _URL, _showtimes

from ...schedule import checked
from .._shared import capture, fetch_cities_main, stable_key
from .parse import movie_url, venue_id

log = logging.getLogger(__name__)


def fetch_pages(session, inputs, cities=(), *, selectors=None):
    films = defaultdict(set)
    checked(selectors, {venue_id(slug) for slug, _, _ in _SITES})
    for slug, city, _ in _SITES:
        if selectors is not None and venue_id(slug) not in selectors:
            continue
        if cities and city not in cities:
            continue
        path = inputs / f"programme-{slug}.html"
        capture(session, f"{_URL}{slug}/", path)
        for film, _ in _showtimes(path.read_text(encoding="utf-8"), city):
            if film.url:
                films[movie_url(film.url, slug)].add(film.url)
    for canonical, links in sorted(films.items()):
        for url in sorted(links):
            try:
                capture(session, url, inputs / f"movie-{stable_key(canonical)}.html")
            except RequestException as exc:
                log.warning("Cinemascenen detail %s unavailable: %s", url, exc)
            else:
                break


if __name__ == "__main__":
    fetch_cities_main("cinemascenen_se", fetch_pages)
