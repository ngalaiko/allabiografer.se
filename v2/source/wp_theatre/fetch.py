"""Capture Capitol Göteborg's listing and production pages."""

from urllib.parse import urljoin

from parse.parsers.wp_theatre import _SITES

from .._shared import capture, film_id, single


def fetch_pages(session, inputs, today, *, selectors=None):
    single(selectors)
    (site,) = _SITES
    page = capture(session, site["url"], inputs / "programme.html")
    urls = {urljoin(site["url"], a["href"]) for a in page.select('.wp_theatre_event_title a[href*="/produktion/"]')}
    if not urls:
        raise ValueError("Missing Capitol Göteborg programme")
    for url in sorted(urls):
        capture(session, url, inputs / f"movie-{film_id(url)}.html")
