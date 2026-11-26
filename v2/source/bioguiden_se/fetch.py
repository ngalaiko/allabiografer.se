"""Capture Bioguiden programmes for its assigned cinemas."""

from parse.parsers.bioguiden_se import _SITES

from .._shared import capture, fetch_cities_main, stable_key


def fetch_pages(session, inputs, cities):
    for url, venue in _SITES.items():
        if not cities or venue.city in cities:
            capture(session, url, inputs / f"programme-{stable_key(url)}.html")


if __name__ == "__main__":
    fetch_cities_main("bioguiden_se", fetch_pages)
