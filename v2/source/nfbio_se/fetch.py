"""Capture Nordisk Film Bio listings and detail pages."""

from parse.parsers.nfbio_se import _BASE, _CINEMAS, _parse_listing
from store import Film

from .._shared import capture, fetch_cities_main, stable_key


def fetch_pages(session, inputs, cities):
    films = set()
    for cinema in _CINEMAS:
        if cities and cinema["city"] not in cities:
            continue
        path = inputs / f"programme-{stable_key(cinema['url'])}.html"
        capture(session, _BASE + cinema["url"], path)
        films.update(
            film.url
            for film in _parse_listing(
                path.read_text(encoding="utf-8"), cinema["name"], cinema["city"], lookup_tmdb=False
            )
            if isinstance(film, Film) and film.url
        )
    for url in sorted(films):
        capture(session, url, inputs / f"movie-{stable_key(url)}.html")


if __name__ == "__main__":
    fetch_cities_main("nfbio_se", fetch_pages)
