"""Capture Svenska Bio's advertised days and source Movie pages."""

import logging

from requests import RequestException

from parse.parsers.svenskabio_se import _CINEMAS, _FEED, _PARAMS, _dates, _showtimes

from .._shared import capture, capture_json, fetch_cities_main, stable_key

log = logging.getLogger(__name__)


def fetch_pages(session, inputs, cities):
    movies = set()
    for city_id, cinema_id, venue in _CINEMAS:
        if cities and venue.city not in cities:
            continue
        params = {**_PARAMS, "cityId": city_id, "cinemaIds": cinema_id}
        first = capture_json(
            session, _FEED, inputs / f"programme-{cinema_id}-all.json", params={**params, "date": "all"}
        )
        seen = set()
        for day in _dates(first, venue):
            payload = (
                first
                if first["date"] == day
                else capture_json(
                    session, _FEED, inputs / f"programme-{cinema_id}-{day}.json", params={**params, "date": day}
                )
            )
            movies.update(film.url for _, _, film, _ in _showtimes(payload, day, venue, seen, lookup_tmdb=False))
    for url in sorted(movies):
        try:
            capture(session, url, inputs / f"movie-{stable_key(url)}.html")
        except RequestException as exc:
            log.warning("Svenska Bio detail %s unavailable: %s", url, exc)


if __name__ == "__main__":
    fetch_cities_main("svenskabio_se", fetch_pages)
