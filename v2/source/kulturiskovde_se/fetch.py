"""Capture the two public Tix listings for Skövde Kulturhus's cinema programmes."""

from parse.parsers.kulturiskovde_se import _SERIES, _SOURCE

from .._shared import capture, fetch_main

TICKETS = "https://tix.se/sv/skovde/buyingflow/tickets/{}/"


def fetch_pages(session, inputs):
    for series in _SERIES:
        capture(session, TICKETS.format(series), inputs / f"series-{series}.html")


if __name__ == "__main__":
    fetch_main(_SOURCE, fetch_pages)
