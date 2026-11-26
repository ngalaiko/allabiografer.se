"""Capture Capitol's dated calendar and film pages."""

from datetime import timedelta

from parse.parsers.capitolbio_se import _DAYS, _SITE, _showtimes

from .._shared import capture, film_id


def fetch_pages(session, inputs, today, *, selectors=None):
    films = set()
    for offset in range(_DAYS):
        day = today + timedelta(days=offset)
        path = inputs / f"programme-{day}.html"
        capture(session, f"{_SITE}/filmer?datum={day}", path)
        films.update(film.url for film, _ in _showtimes(path.read_text(encoding="utf-8"), day))
    for url in sorted(films):
        capture(session, url, inputs / f"movie-{film_id(url)}.html")
