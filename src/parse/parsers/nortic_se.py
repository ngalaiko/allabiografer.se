"""nortic.se — public JSON API, Bio category events only."""

import logging
from collections.abc import Iterator
from datetime import datetime

import requests

from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Screening, Venue

log = logging.getLogger(__name__)

_API = "https://www.nortic.se/api/json/shows"


def parse() -> Iterator[Screening | Venue]:
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; bio-parser/1.0)"

    resp = session.get(_API, timeout=30)
    resp.raise_for_status()
    bio_events = [e for e in resp.json().get("events", []) if e.get("category") == "Bio"]
    log.info("nortic.se: %d bio events", len(bio_events))

    seen_venues: set[tuple[str, str]] = set()

    for event in bio_events:
        film_title = event.get("title", "")
        if not film_title:
            continue
        tmdb_id = _tmdb(film_title)
        if tmdb_id is None:
            continue

        count = 0
        for show in event.get("shows") or []:
            cinema_name = show.get("arenaName", "")
            raw_city = show.get("arenaCity", "")
            # API sometimes returns city in ALL-CAPS (e.g. "ELLÖS")
            city = raw_city.title() if raw_city == raw_city.upper() else raw_city
            address = show.get("arenaAddress", "")
            ticket_url = show.get("link", "")
            raw_dt = show.get("startDate", "")

            if not cinema_name or not raw_dt or not ticket_url:
                continue

            venue_key = (cinema_name, city)
            if venue_key not in seen_venues:
                seen_venues.add(venue_key)
                yield Venue(name=cinema_name, city=city, address=address)

            try:
                dt = datetime.strptime(raw_dt, "%Y-%m-%d %H:%M")
            except ValueError:
                log.warning("bad startDate %r for %r", raw_dt, film_title)
                continue

            yield Screening(
                tmdb_id=tmdb_id,
                date=dt.date(),
                time=dt.time(),
                cinema_name=cinema_name,
                city=city,
                ticket_url=ticket_url,
            )
            count += 1

        if count:
            log.info("  %s: %d screenings", film_title, count)
