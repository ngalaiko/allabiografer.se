"""Capture Hallunda's programme, screening articles and linked Tickster pages."""

from functools import partial
from urllib.parse import urljoin

from allabiografer.sources.hallundafolketshus_se import site as site

from .._shared import single
from ..tickster_se.pages import Pages, year_for_month

SOURCE = "hallundafolketshus_se"


def articles(pages, today):
    for row in site._events(pages.text(site._URL), year_for_month=partial(year_for_month, today)):
        _, day, _, url, *_ = row
        if day >= today:
            html = pages.text(url, optional=True)
            link = site._ticket(html) if html else ""
            yield row, html, urljoin(url, link) if link else ""


def fetch_pages(session, inputs, today, *, selectors=None):
    single(selectors)
    session.headers["User-Agent"] = "Mozilla/5.0"
    pages = Pages(inputs, session)
    for _, _, ticket in articles(pages, today):
        if ticket:
            pages.text(ticket, optional=True)
