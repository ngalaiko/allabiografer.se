"""Capture Capitol's dated calendar and film pages."""

from datetime import datetime, timedelta

from parse.parsers.capitolbio_se import _DAYS, _SITE, _showtimes

from .._shared import STOCKHOLM, capture, fetch_main, film_id


def fetch_pages(session, inputs):
    today = datetime.fromtimestamp(int(inputs.parents[1].name), STOCKHOLM).date()
    films = set()
    for offset in range(_DAYS):
        day = today + timedelta(days=offset)
        path = inputs / f"programme-{day}.html"
        capture(session, f"{_SITE}/filmer?datum={day}", path)
        films.update(film.url for film, _ in _showtimes(path.read_text(encoding="utf-8"), day))
    for url in sorted(films):
        capture(session, url, inputs / f"movie-{film_id(url)}.html")


if __name__ == "__main__":
    fetch_main("capitolbio_se", fetch_pages)
