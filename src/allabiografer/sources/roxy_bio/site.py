"""Roxy Kristianstad's public My Cloud Cinema programme."""

from allabiografer.model import Venue

_BASE = "https://boka.roxy.bio"
_VENUE = Venue(name="Roxy Bio", city="Kristianstad", address="Tivoligatan 3D")


def _showtimes(rows):
    # The cinema's events feed includes locked bookings and its film quiz.
    return [
        row
        for row in rows
        if not row["show_locked"]
        and row["title"].strip()
        and not row["title"].strip().casefold().startswith("filmquiz")
    ]
