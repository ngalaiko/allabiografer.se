"""Save the cinema homepages containing the Folkets Hus och Parker programme."""

from parse.parsers.folkets_hus_och_parker import _SITES

from ...schedule import checked
from .._shared import capture


def fetch_pages(session, inputs, today, *, selectors=None):
    checked(selectors, {site.source for site in _SITES})
    for site in _SITES:
        if selectors is not None and site.source not in selectors:
            continue
        capture(session, f"https://{site.host}/", inputs / f"{site.source}.html")
