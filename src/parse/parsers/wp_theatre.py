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
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

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

_SOURCE = "wp_theatre"
_SITES = [
    {"city": "Göteborg", "name": "Capitol", "url": "https://www.capitolgbg.se/", "address": "Skanstorget 1"},
]

# Post categories that label a programme series rather than a genre.
_NOT_GENRES = {"cinemateket", "unga-cinemateket"}
# Category slugs the theme strips diacritics from.
_GENRE_NAMES = {"dokumentar": "Dokumentär"}

# Programme series prefixed to the film title, e.g. "Cinemateket: Blade Runner".
_SERIES_PREFIX = re.compile(r"^(?:unga\s+)?cinemateket\s*:\s*", re.IGNORECASE)
# "1 tim 46 min"
_HOURS = re.compile(r"(\d+)\s*tim")
_MINUTES = re.compile(r"(\d+)\s*min")


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


def _lookup_title(title: str) -> str:
    """Film title without the programme series it is listed under."""
    return _SERIES_PREFIX.sub("", title).strip()


def _parse_runtime(text: str) -> int | None:
    """Runtime in minutes from "1 tim 46 min"."""
    hours = _HOURS.search(text)
    minutes = _MINUTES.search(text)
    if not hours and not minutes:
        return None
    return int(hours.group(1) if hours else 0) * 60 + int(minutes.group(1) if minutes else 0)


def _meta(soup: BeautifulSoup, prop: str) -> str:
    el = soup.select_one(f'meta[property="{prop}"][content]')
    return el.get("content", "").strip() if el else ""


def _genres(soup: BeautifulSoup) -> list[str]:
    """Genres from the production post's category classes."""
    post = soup.select_one("[id^=post-]")
    classes = post.get("class") or [] if post else []
    slugs = [c.removeprefix("category-") for c in classes if c.startswith("category-")]
    return [_GENRE_NAMES.get(s, s.replace("-", " ").capitalize()) for s in slugs if s not in _NOT_GENRES]


def _synopsis(soup: BeautifulSoup) -> tuple[str, int | None]:
    """Description and runtime from the post body, which ends at the runtime line."""
    body = soup.select_one(".entry-content") or soup.select_one(".post-entry")
    if body is None:
        return "", None

    paragraphs: list[str] = []
    for p in body.select("p"):
        # Showtime remarks live inside the listing, not the description.
        if p.find_parent(class_="wpt_listing"):
            continue
        text = p.get_text(" ", strip=True)
        runtime = _parse_runtime(text)
        if runtime:
            return " ".join(paragraphs), runtime
        if text:
            paragraphs.append(text)
    return " ".join(paragraphs), None


def _film(soup: BeautifulSoup, title: str) -> tuple[Film, int | None]:
    """Film metadata a production page carries, and its runtime."""
    overview, runtime = _synopsis(soup)
    return (
        _films.make(
            _SOURCE,
            title,
            overview=overview,
            runtime=runtime,
            genres=_genres(soup),
            poster_url=_meta(soup, "og:image:secure_url") or _meta(soup, "og:image"),
            url=_meta(soup, "og:url"),
        ),
        runtime,
    )


def _parse_production(html: str, site: dict) -> Iterator[Screening | Film]:
    """Yield the film listed on one production page, then every showtime."""
    psoup = BeautifulSoup(html, "html.parser")

    h1 = psoup.select_one("h1.wp_theatre_production_title") or psoup.select_one("h1")
    film_title = h1.get_text(strip=True) if h1 else ""
    if not film_title:
        return

    film, runtime = _film(psoup, film_title)
    yield film
    tmdb_id = _tmdb(_lookup_title(film_title), runtime=runtime)

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
            title=film_title,
            date=d,
            time=t,
            ticket_url=ticket_url,
            cinema_name=site["name"],
            city=site["city"],
            screen=venue_el.get_text(strip=True) if venue_el else "",
            film_key=film.key,
        )


def parse() -> Iterator[Screening | Venue | Film]:
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; bio-parser/1.0)"

    for site in _SITES:
        yield Venue(name=site["name"], city=site["city"], address=site.get("address", ""))
        log.info("wp_theatre: fetching %s", site["name"])
        yield from _parse_site(session, site)


def _parse_site(session: requests.Session, site: dict) -> Iterator[Screening | Film]:
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
    seen_films: set[str] = set()
    for url in sorted(prod_urls):
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
        except requests.RequestException:
            log.exception("error fetching %s", url)
            raise

        for item in _parse_production(resp.text, site):
            if isinstance(item, Film):
                if item.key not in seen_films:
                    seen_films.add(item.key)
                    yield _films.register(item, session=session)
                continue
            yield item
            count += 1

    log.info("  %s: %d screenings", site["name"], count)
