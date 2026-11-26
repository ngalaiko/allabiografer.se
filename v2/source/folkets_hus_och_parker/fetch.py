"""Save the cinema homepages containing the Folkets Hus och Parker programme."""

from parse.parsers.folkets_hus_och_parker import _SITES

from ...schedule import checked
from .._shared import capture, fetch_cities_main


def fetch_pages(session, inputs, cities=(), *, selectors=None):
    checked(selectors, {site.source for site in _SITES})
    for site in _SITES:
        if selectors is not None and site.source not in selectors:
            continue
        if not cities or site.city in cities:
            capture(session, f"https://{site.host}/", inputs / f"{site.source}.html")


if __name__ == "__main__":
    fetch_cities_main("folkets_hus_och_parker", fetch_pages)
