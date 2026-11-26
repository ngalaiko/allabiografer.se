"""Capture Hallunda's programme, screening articles and linked Tickster pages."""

from functools import partial
from urllib.parse import urljoin

from parse.parsers import hallundafolketshus_se as site

from .._shared import fetch_main
from ..tickster_se.pages import Pages, capture_day, year_for_month

SOURCE = "hallundafolketshus_se"


def articles(pages, today):
    for row in site._events(pages.text(site._URL), year_for_month=partial(year_for_month, today)):
        _, day, _, url, *_ = row
        if day >= today:
            html = pages.text(url, optional=True)
            link = site._ticket(html) if html else ""
            yield row, html, urljoin(url, link) if link else ""


def fetch_pages(session, inputs):
    session.headers["User-Agent"] = "Mozilla/5.0"
    pages = Pages(inputs, session)
    for _, _, ticket in articles(pages, capture_day(inputs)):
        if ticket:
            pages.text(ticket, optional=True)


if __name__ == "__main__":
    fetch_main(SOURCE, fetch_pages)
