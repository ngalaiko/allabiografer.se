"""Capture Bioguiden programmes for its assigned cinemas."""

from parse.parsers.bioguiden_se import _SITES

from ...schedule import checked
from .._shared import capture, fetch_cities_main, stable_key


def fetch_pages(session, inputs, cities=(), *, selectors=None):
    checked(selectors, {stable_key(url) for url in _SITES})
    for url, venue in _SITES.items():
        if selectors is not None and stable_key(url) not in selectors:
            continue
        if not cities or venue.city in cities:
            capture(session, url, inputs / f"programme-{stable_key(url)}.html")


if __name__ == "__main__":
    fetch_cities_main("bioguiden_se", fetch_pages)
