"""nfbio.se — Nordisk Film Bio (Uppsala + Malmö), Drupal AJAX endpoints."""

import json
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

_BASE = "https://www.nfbio.se"
_CINEMAS = [
    {
        "city": "Uppsala",
        "name": "Nordisk Film Bio Uppsala",
        "url": "/biograf/uppsala?city=uppsala",
        "city_param": "uppsala",
        "address": "Vaksalagatan 3",
    },
    {
        "city": "Malmö",
        "name": "Nordisk Film Bio Mobilia",
        "url": "/nordisk-film-bio-mobilia?city=malmo",
        "city_param": "malmo",
        "address": "Per Albin Hanssons väg 40",
    },
]


def _parse_date_text(text: str) -> date | None:
    m = re.match(r"\w+,?\s*(\d{1,2})/(\d{1,2})", text.strip())
    if not m:
        return None
    month = int(m.group(2))
    return date(infer_year(month), month, int(m.group(1)))


def _parse_time_text(text: str) -> time | None:
    m = re.match(r"(\d{1,2})\.(\d{2})", text.strip())
    return time(int(m.group(1)), int(m.group(2))) if m else None


def _discover_film_slugs(session: requests.Session, page_url: str) -> list[str]:
    """Get film URL slugs from a cinema listing page."""
    resp = session.get(page_url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    slugs = []
    seen = set()

    # Both page types: find film links and strip query params to get slugs
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        slug = re.sub(r"\?.*", "", href)
        if (
            slug
            and slug.startswith("/")
            and slug != "/"
            and "screening" not in slug
            and "ajax" not in slug
            and "biograf" not in slug
            and slug not in seen
        ):
            # Verify it looks like a film slug (single path segment)
            parts = slug.strip("/").split("/")
            if len(parts) == 1 and len(parts[0]) > 2:
                seen.add(slug)
                slugs.append(slug)

    return slugs


def _fetch_film_screenings(
    session: requests.Session,
    film_slug: str,
    city_param: str,
    cinema_name: str,
    city: str,
) -> Iterator[Screening]:
    """Fetch screenings for one film via the AJAX endpoint."""
    ajax_url = f"{_BASE}{film_slug}/ajax/full/ml-movie-details?city={city_param}"
    resp = session.get(ajax_url, timeout=15, headers={"X-Requested-With": "XMLHttpRequest"})
    resp.raise_for_status()

    commands = json.loads(resp.text)
    for cmd in commands:
        if cmd.get("command") != "insert" or not cmd.get("data"):
            continue

        soup = BeautifulSoup(cmd["data"], "html.parser")

        # Film title from the fragment
        title_el = soup.select_one(".node-title, .field--name-title span")
        film_title = title_el.get_text(strip=True) if title_el else ""
        if not film_title:
            # Derive from slug: /super-mario-galaxy-filmen -> Super Mario Galaxy Filmen
            film_title = film_slug.strip("/").replace("-", " ").title()

        tmdb_id = _tmdb(film_title)
        if tmdb_id is None:
            return

        for slide in soup.select(".slick__slide"):
            d = _parse_date_text(slide.get_text(" ", strip=True))
            if not d:
                continue

            for btn in slide.select(".movies-screenings-button-link"):
                href = btn.get("href", "")
                if not href:
                    continue
                if not href.startswith("http"):
                    href = _BASE + href

                time_el = btn.select_one(".time")
                t = _parse_time_text(time_el.get_text(strip=True)) if time_el else None
                if not t:
                    continue

                room_el = btn.select_one(".room")
                version_el = btn.select_one(".version")

                yield Screening(
                    tmdb_id=tmdb_id,
                    date=d,
                    time=t,
                    ticket_url=href,
                    cinema_name=cinema_name,
                    city=city,
                    screen=room_el.get_text(strip=True) if room_el else "",
                    format=" ".join(version_el.get_text(" ", strip=True).split()) if version_el else "",
                )


def parse() -> Iterator[Screening | Venue]:
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; bio-parser/1.0)"

    for cinema in _CINEMAS:
        city = cinema["city"]
        name = cinema["name"]
        page_url = _BASE + cinema["url"]

        yield Venue(name=name, city=city, address=cinema.get("address", ""))

        log.info("nfbio.se: discovering films for %s", name)
        slugs = _discover_film_slugs(session, page_url)
        log.info("  %d films found", len(slugs))

        count = 0
        for slug in slugs:
            try:
                for s in _fetch_film_screenings(session, slug, cinema["city_param"], name, city):
                    yield s
                    count += 1
            except Exception as exc:
                log.warning("  error fetching %s: %s", slug, exc)

        log.info("  %s: %d screenings", name, count)
