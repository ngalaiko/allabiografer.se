"""Capture Tickster organiser listings and candidate event pages."""

from datetime import timedelta

from parse.parsers import _tickster
from parse.parsers.tickster_se import _BASE, _NOT_A_SHOWING, _SITES

from ...schedule import checked
from .._shared import fetch_main
from .pages import Pages, capture_day

SOURCE = "tickster_se"


def candidates(pages, today, selectors=None):
    checked(selectors, {site.organiser.split("/", 1)[0] for site in _SITES})
    seen = set()
    for site in _SITES:
        if selectors is not None and site.organiser.split("/", 1)[0] not in selectors:
            continue
        url = _BASE + site.organiser
        visited = set()
        while url:
            if url in visited:
                raise ValueError(f"Tickster pagination loop: {url}")
            visited.add(url)
            events, url = _tickster.listing(pages.text(url))
            for item in events:
                if (
                    item.url not in seen
                    and today <= item.date <= today + timedelta(days=365)
                    and not _NOT_A_SHOWING.search(item.title)
                ):
                    seen.add(item.url)
                    yield site, item


def fetch_pages(session, inputs, *, selectors=None):
    pages = Pages(inputs, session)
    for _, item in candidates(pages, capture_day(inputs), selectors):
        pages.text(item.url, optional=True)


if __name__ == "__main__":
    fetch_main(SOURCE, fetch_pages)
