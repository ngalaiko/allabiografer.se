"""bio.se — JSON API, all cinemas in one pass."""

import logging
from collections.abc import Iterator
from datetime import datetime

import requests

from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Screening, Venue

log = logging.getLogger(__name__)

_API = "https://bio.se/api"


def _ticket_url(payment_link: str) -> str:
    """Build a ticket URL from the API's payment_link field."""
    if not payment_link:
        return ""
    if payment_link.startswith(("http://", "https://")):
        return payment_link
    return f"https://bio.se{payment_link}"


def parse() -> Iterator[Screening]:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; bio-parser/1.0)", "Accept": "application/json"})

    resp = session.get(f"{_API}/cinemas", timeout=30)
    resp.raise_for_status()
    cinemas = resp.json().get("cinemas", [])
    log.info("bio.se: %d cinemas", len(cinemas))

    for cinema in cinemas:
        cinema_id = cinema["id"]
        cinema_name = cinema["title"]
        city = cinema.get("city", "") or cinema_name.split()[0]
        address = cinema.get("street_address", "")

        yield Venue(name=cinema_name, city=city, address=address)

        resp = session.post(f"{_API}/cinemas/films", json={"cinemaId": cinema_id}, timeout=15)
        resp.raise_for_status()

        count = 0
        for entry in resp.json().get("movies", []):
            movie = entry.get("movie", {})
            film_title = movie.get("title", "")
            if not film_title:
                continue
            tmdb_id = _tmdb(film_title)
            if tmdb_id is None:
                continue
            for sess in entry.get("sessions", []):
                raw = sess.get("show_date_time", "")
                if not raw:
                    continue
                dt = datetime.fromisoformat(raw)
                url = _ticket_url(sess.get("payment_link", ""))
                if not url:
                    continue
                yield Screening(
                    tmdb_id=tmdb_id,
                    date=dt.date(),
                    time=dt.time(),
                    cinema_name=cinema_name,
                    city=city,
                    language=sess.get("language", ""),
                    subtitles=sess.get("text", ""),
                    format=sess.get("format", ""),
                    screen=sess.get("screen_name", ""),
                    ticket_url=url,
                )
                count += 1

        if count:
            log.info("  %s (%s): %d screenings", cinema_name, city, count)
