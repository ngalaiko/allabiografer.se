"""Capture Filmhuset Palladium's programme and Tickster-linked event pages."""

from urllib.parse import urljoin

from parse.parsers.palladiumbio_se import _SOURCE, _URL

from .._shared import capture, fetch_main, stable_key


def fetch_pages(session, inputs):
    page = capture(session, _URL, inputs / "programme.html")
    urls = dict.fromkeys(urljoin(_URL, a["href"]) for a in page.select("table.tableBioprogram td.title a[href]"))
    for url in urls:
        capture(session, url, inputs / f"event-{stable_key(url)}.html")


if __name__ == "__main__":
    fetch_main(_SOURCE, fetch_pages)
