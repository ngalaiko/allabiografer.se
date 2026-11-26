"""Capture Kiviks Bio's WordPress Events Manager listing and event pages."""

from urllib.parse import urljoin

from parse.parsers.kiviksbio_se import _SOURCE, _URL

from .._shared import capture, fetch_main, film_id


def fetch_pages(session, inputs):
    page = capture(session, _URL, inputs / "programme.html")
    urls = dict.fromkeys(urljoin(_URL, link["href"]) for link in page.select(".em-item-title a[href]"))
    for url in urls:
        capture(session, url, inputs / f"event-{film_id(url)}.html")


if __name__ == "__main__":
    fetch_main(_SOURCE, fetch_pages)
