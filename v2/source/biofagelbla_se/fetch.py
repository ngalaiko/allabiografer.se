"""Capture Fågel Blå's programme and film pages."""

from urllib.parse import urljoin, urlsplit

from .._shared import capture, film_id

BASE = "https://biofagelbla.se"
SOURCE = "biofagelbla_se"


def fetch_pages(session, inputs, today, *, selectors=None):
    page = capture(session, f"{BASE}/program/", inputs / "programme.html")
    cards = page.select('.js-movie-listing-by-date article a[href*="showtime="]')
    movies = {}
    for card in cards:
        booking = urlsplit(urljoin(BASE, card["href"]))
        if booking.netloc != urlsplit(BASE).netloc:
            raise ValueError(f"Unexpected Fågel Blå booking URL: {card['href']}")
        movies[f"{BASE}{booking.path}"] = None
    for movie in movies:
        capture(session, movie, inputs / f"movie-{film_id(movie)}.html")
