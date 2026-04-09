"""doclounge.se — Doc Lounge documentary screenings, Next.js SSR with __NEXT_DATA__."""

import json
import logging
import re
from collections.abc import Iterator
from datetime import date, time

import requests
from bs4 import BeautifulSoup

from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Screening, Venue

log = logging.getLogger(__name__)

_URL = "https://www.doclounge.se/events-screenings"

# Only Swedish cities — Doc Lounge also operates in Finland but we skip those.
_SWEDISH_CITIES = {
    "goteborg": "Göteborg",
    "helsingborg": "Helsingborg",
    "landskrona": "Landskrona",
    "lund": "Lund",
    "malmo": "Malmö",
    "ostersund": "Östersund",
    "umea": "Umeå",
    "varberg": "Varberg",
}


def parse() -> Iterator[Screening | Venue]:
    resp = requests.get(_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0 (compatible; bio-parser/1.0)"})
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        log.warning("doclounge.se: no __NEXT_DATA__ found")
        return

    data = json.loads(script.string)
    events = data.get("props", {}).get("pageProps", {}).get("events", {}).get("nodes", [])
    log.info("doclounge.se: %d events found", len(events))

    yielded_venues: set[tuple[str, str]] = set()

    for event in events:
        content = event.get("gqlEventContent") or {}

        # Date & time
        date_str = content.get("date", "")
        time_str = content.get("time", "")
        if not date_str or not time_str:
            continue

        try:
            d = date.fromisoformat(date_str)
        except ValueError:
            continue

        m = re.match(r"(\d{1,2}):(\d{2})", time_str)
        if not m:
            continue
        t = time(int(m.group(1)), int(m.group(2)))

        # City — filter to Swedish cities only
        city_nodes = event.get("cities", {}).get("nodes", [])
        if not city_nodes:
            continue
        city_slug = city_nodes[0].get("slug", "")
        city = _SWEDISH_CITIES.get(city_slug)
        if not city:
            continue

        # Venue & address
        address_full = content.get("address", "")
        # Address format is typically "Venue Name, Street, City"
        # Use the first part as cinema name
        parts = [p.strip() for p in address_full.split(",")]
        cinema_name = parts[0] if parts else "Doc Lounge"

        # Ticket URL
        ticket_url = (content.get("goToEvent") or {}).get("url", "")
        if not ticket_url:
            continue

        # Film title — from linked movie or event title
        movie = content.get("movie") or {}
        title = movie.get("title") or event.get("title", "")
        if not title:
            continue

        tmdb_id = _tmdb(title)
        if tmdb_id is None:
            continue

        # Yield venue if not seen
        venue_key = (city, cinema_name)
        if venue_key not in yielded_venues:
            yielded_venues.add(venue_key)
            address = ", ".join(parts[1:]).strip() if len(parts) > 1 else ""
            yield Venue(name=cinema_name, city=city, address=address)

        yield Screening(
            tmdb_id=tmdb_id,
            date=d,
            time=t,
            ticket_url=ticket_url,
            cinema_name=cinema_name,
            city=city,
        )
