"""Capture the two public Tix listings for Skövde Kulturhus's cinema programmes."""

from parse.parsers.kulturiskovde_se import _SERIES

from .._shared import capture, single

TICKETS = "https://tix.se/sv/skovde/buyingflow/tickets/{}/"


def fetch_pages(session, inputs, today, *, selectors=None):
    single(selectors)
    for series in _SERIES:
        capture(session, TICKETS.format(series), inputs / f"series-{series}.html")
