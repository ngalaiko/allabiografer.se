"""Capture Bioguiden programmes for its assigned cinemas."""

from allabiografer.sources.bioguiden_se.site import _SITES

from ...schedule import checked
from .._shared import capture, stable_key


def fetch_pages(session, inputs, today, *, selectors=None):
    checked(selectors, {stable_key(url) for url in _SITES})
    for url in _SITES:
        if selectors is not None and stable_key(url) not in selectors:
            continue
        capture(session, url, inputs / f"programme-{stable_key(url)}.html")
