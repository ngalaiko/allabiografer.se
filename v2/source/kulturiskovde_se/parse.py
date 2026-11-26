"""Replay Odeon dates and titles from the two saved Tix listings."""

from datetime import datetime

from parse.parsers.kulturiskovde_se import _SERIES, _VENUE, _showtimes

from .._shared import STOCKHOLM, facts, read_page, stable_key
from .fetch import TICKETS

# Tix event IDs identify the reviewed December 2026 bookings, not future screenings with the same title.
MOVIE_LINKS = {
    "129559": "https://bio.se/movie/42258",  # Couture, in the Swedish theatrical release window.
    "129560": "https://bio.se/movie/47019",  # Dagbio also lists A Sad and Beautiful World.
    "129561": "https://www.filmstaden.se/film/pillion",
    "129670": "https://bio.se/movie/4323",  # The organizer's description identifies Molly and Edison.
}


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
                ("biograf-odeon-skovde", _VENUE.name, _VENUE.address, _VENUE.city),
                show,
                start,
                ticket,
                *facts(),
                stable_key(title.casefold()),
                capture,
                {"name": title, **({"sameAs": MOVIE_LINKS[event]} if event in MOVIE_LINKS else {})},
            )
