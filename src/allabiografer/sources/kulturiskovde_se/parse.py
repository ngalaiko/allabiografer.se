"""Replay Odeon dates and titles from the two saved Tix listings."""

from datetime import datetime

from allabiografer.sources.kulturiskovde_se.site import _SERIES, _VENUE, _showtimes

from .._shared import STOCKHOLM, facts, read_page, stable_key
from .fetch import TICKETS


def rows(inputs, today):
    seen = set()
    for series in _SERIES:
        capture = f"series-{series}.html"
        ticket = TICKETS.format(series)
        for event, title, day, time in _showtimes(read_page(inputs / capture)):
            if day < today or not title:
                continue
            start = datetime.combine(day, time, STOCKHOLM)
            show = stable_key(event) if event else stable_key(title, start.isoformat())
            if show in seen:
                continue
            seen.add(show)
            yield (
                (None, _VENUE.name, _VENUE.address, _VENUE.city),
                show,
                start,
                ticket,
                *facts(),
                stable_key(title.casefold()),
                capture,
                {"name": title},
                capture,
            )
