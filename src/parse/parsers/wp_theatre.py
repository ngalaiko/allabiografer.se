"""WordPress Theater plugin sites — wp_theatre_event blocks.

Discovers films from the homepage, then crawls each production page
for full screening data (dates, times, venues, ticket links).
"""

import logging
import re
from collections.abc import Iterator
from datetime import date, time

import requests
from bs4 import BeautifulSoup

from parse._util import infer_year
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Screening, Venue

log = logging.getLogger(__name__)

_MONTHS = {
    "januari": 1,
    "februari": 2,
    "mars": 3,
    "april": 4,
    "maj": 5,
    "juni": 6,
    "juli": 7,
    "augusti": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "december": 12,
}

_SITES = [
    {"city": "Göteborg", "name": "Capitol", "url": "https://www.capitolgbg.se/", "address": "Skanstorget 1"},
]


def _parse_datetime(text: str) -> tuple[date, time] | None:
    """Parse 'tisdag 31 mars 16:00' or '1 april, 2026 16:00'."""
    # "weekday DD month HH:MM"
    m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{1,2}):(\d{2})", text.strip())
    if not m:
        return None
    day = int(m.group(1))
    month = _MONTHS.get(m.group(2).lower())
    if not month:
        return None
    # Year might be present
    ym = re.search(r"(\d{4})", text)
    year = int(ym.group(1)) if ym else infer_year(month)
    return date(year, month, day), time(int(m.group(3)), int(m.group(4)))


def parse() -> Iterator[Screening | Venue]:
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; bio-parser/1.0)"

    for site in _SITES:
        yield Venue(name=site["name"], city=site["city"], address=site.get("address", ""))
        log.info("wp_theatre: fetching %s", site["name"])
        yield from _parse_site(session, site)


def _parse_site(session: requests.Session, site: dict) -> Iterator[Screening]:
    resp = session.get(site["url"], timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Discover production page URLs from event title links
    prod_urls: set[str] = set()
    for a in soup.select(".wp_theatre_event_title a[href]"):
        href = a.get("href", "")
        if href and "/produktion/" in href:
            prod_urls.add(href)

    log.info("  %d productions found", len(prod_urls))

    count = 0
    for url in sorted(prod_urls):
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
        except Exception as exc:
            log.warning("  error fetching %s: %s", url, exc)
            continue

        psoup = BeautifulSoup(resp.text, "html.parser")

        # Film title from page heading
        h1 = psoup.select_one("h1.wp_theatre_production_title") or psoup.select_one("h1")
        film_title = h1.get_text(strip=True) if h1 else ""
        if not film_title:
            continue
        tmdb_id = _tmdb(film_title)
        if tmdb_id is None:
            continue

        for ev in psoup.select(".wp_theatre_event"):
            dt_el = ev.select_one(".wp_theatre_event_datetime")
            venue_el = ev.select_one(".wp_theatre_event_venue")
            ticket_el = ev.select_one(".wp_theatre_event_tickets_url")

            if not dt_el:
                continue
            parsed = _parse_datetime(dt_el.get_text(strip=True))
            if not parsed:
                continue
            d, t = parsed

            ticket_url = ticket_el.get("href", "") if ticket_el else ""
            if not ticket_url:
                continue

            yield Screening(
                tmdb_id=tmdb_id,
                date=d,
                time=t,
                ticket_url=ticket_url,
                cinema_name=site["name"],
                city=site["city"],
                screen=venue_el.get_text(strip=True) if venue_el else "",
            )
            count += 1

    log.info("  %s: %d screenings", site["name"], count)
