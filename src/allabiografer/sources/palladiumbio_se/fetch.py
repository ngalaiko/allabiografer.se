"""Capture Filmhuset Palladium's programme and Tickster-linked event pages."""

from urllib.parse import urljoin

from allabiografer.sources.palladiumbio_se.site import _URL

from .._shared import capture, single, stable_key


def fetch_pages(session, inputs, today, *, selectors=None):
    single(selectors)
    page = capture(session, _URL, inputs / "programme.html")
    urls = dict.fromkeys(urljoin(_URL, a["href"]) for a in page.select("table.tableBioprogram td.title a[href]"))
    for url in urls:
        capture(session, url, inputs / f"event-{stable_key(url)}.html")
