"""nortic.se — public JSON API, Bio category events only."""

import html
import logging
import re
from collections.abc import Iterator
from datetime import date, time

import requests

from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue, film_key

log = logging.getLogger(__name__)

_SOURCE = "nortic_se"
_API = "https://www.nortic.se/api/json/shows"
# Venues file cinema screenings under either label.
_CATEGORIES = {"Bio", "Film"}


def parse() -> Iterator[Screening | Venue | Film]:
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; bio-parser/1.0)"

    resp = session.get(_API, timeout=30)
    resp.raise_for_status()
    for item in _parse_payload(resp.json()):
        yield _films.register(item, session=session) if isinstance(item, Film) else item


def _text(raw: str | None) -> str:
    """Plain text from an HTML fragment."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", raw or "")).split())


def _runtime(event: dict) -> int | None:
    """Longest non-zero show length, in minutes."""
    lengths = [int(s.get("playTimeInMinutes") or 0) for s in event.get("shows") or []]
    return max(lengths) or None


def _film(event: dict) -> Film:
    """Film metadata carried by one event.

    The API exposes no poster: its images are 16:9 event banners.
    """
    return _films.make(
        _SOURCE,
        event["title"],
        overview=_text(event.get("description")) or _text(event.get("shortDescription")),
        runtime=_runtime(event),
        url=event.get("link") or "",
    )


def _merge(old: Film, new: Film) -> Film:
    """Fill the fields *old* lacks from *new* — the same film under two organizers."""
    return Film(
        key=old.key,
        source=old.source,
        title=old.title,
        overview=old.overview or new.overview,
        runtime=old.runtime or new.runtime,
        url=old.url or new.url,
    )


def _parse_payload(data: dict) -> Iterator[Screening | Venue | Film]:
    bio_events = [e for e in data["events"] if e.get("category") in _CATEGORIES and e.get("title")]
    log.info("nortic.se: %d bio events", len(bio_events))

    films: dict[str, Film] = {}
    for event in bio_events:
        film = _film(event)
        films[film.key] = _merge(films[film.key], film) if film.key in films else film
    yield from films.values()

    seen_venues: set[tuple[str, str]] = set()

    for event in bio_events:
        film_title = event["title"]
        tmdb_id = _tmdb(film_title)
        key = film_key(_SOURCE, film_title)

        count = 0
        for show in event.get("shows") or []:
            cinema_name = show.get("arenaName") or ""
            raw_city = show.get("arenaCity") or ""
            # API sometimes returns city in ALL-CAPS (e.g. "ELLÖS")
            city = raw_city.title() if raw_city == raw_city.upper() else raw_city
            address = show.get("arenaAddress") or ""
            ticket_url = show.get("link") or ""
            raw_dt = show.get("startDate") or ""

            if not cinema_name or not raw_dt or not ticket_url:
                continue

            venue_key = (cinema_name, city)
            if venue_key not in seen_venues:
                seen_venues.add(venue_key)
                yield Venue(name=cinema_name, city=city, address=address)

            try:
                date_str, time_str = raw_dt.split(" ", 1)
                h, m = time_str.split(":")
                dt_date = date.fromisoformat(date_str)
                dt_time = time(int(h), int(m))
            except (ValueError, AttributeError):
                log.warning("bad startDate %r for %r", raw_dt, film_title)
                continue

            yield Screening(
                tmdb_id=tmdb_id,
                title=film_title,
                date=dt_date,
                time=dt_time,
                cinema_name=cinema_name,
                city=city,
                ticket_url=ticket_url,
                film_key=key,
            )
            count += 1

        if count:
            log.info("  %s: %d screenings", film_title, count)
