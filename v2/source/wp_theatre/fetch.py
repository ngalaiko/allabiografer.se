"""Capture Capitol Göteborg's listing and production pages."""

from urllib.parse import urljoin

from parse.parsers.wp_theatre import _SITES

from .._shared import capture, fetch_main, film_id


def fetch_pages(session, inputs):
    (site,) = _SITES
    page = capture(session, site["url"], inputs / "programme.html")
    urls = {urljoin(site["url"], a["href"]) for a in page.select('.wp_theatre_event_title a[href*="/produktion/"]')}
    if not urls:
        raise ValueError("Missing Capitol Göteborg programme")
    for url in sorted(urls):
        capture(session, url, inputs / f"movie-{film_id(url)}.html")


if __name__ == "__main__":
    fetch_main("wp_theatre", fetch_pages)
