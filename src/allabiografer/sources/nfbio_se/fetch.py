"""Capture Nordisk Film Bio listings and detail pages."""

from allabiografer.model import Film
from allabiografer.sources.nfbio_se.site import _BASE, _CINEMAS, _parse_listing

from ...schedule import checked
from .._shared import capture, stable_key


def venue_id(url):
    return stable_key(url)


def fetch_pages(session, inputs, today, *, selectors=None):
    films = set()
    checked(selectors, {venue_id(cinema["url"]) for cinema in _CINEMAS})
    for cinema in _CINEMAS:
        if selectors is not None and venue_id(cinema["url"]) not in selectors:
            continue
        path = inputs / f"programme-{stable_key(cinema['url'])}.html"
        capture(session, _BASE + cinema["url"], path)
        films.update(
            film.url
            for film in _parse_listing(path.read_text(encoding="utf-8"), cinema["name"], cinema["city"])
            if isinstance(film, Film) and film.url
        )
    for url in sorted(films):
        capture(session, url, inputs / f"movie-{stable_key(url)}.html")
