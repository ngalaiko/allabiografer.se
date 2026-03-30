"""fhbracke.se — Bräcke Bio, WordPress with "Title weekday DD month HH:MM" format."""

import re
from collections.abc import Iterator
from datetime import date, time

import requests
from bs4 import BeautifulSoup

from parse._util import infer_year
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Screening, Venue

_URL = "https://fhbracke.se/bio/"
_CINEMA = "Bräcke Bio"
_CITY = "Bräcke"
_ADDRESS = "Hantverksgatan 27"

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


def parse() -> Iterator[Screening | Venue]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)
    resp = requests.get(_URL, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    seen: set[tuple[str, str]] = set()

    for a in soup.find_all("a", href=re.compile(r"/film/")):
        href = a.get("href", "")
        # Title + date is in a parent container, not the link itself
        container = a
        for _ in range(6):
            container = container.parent
            if not container:
                break
            if re.search(r"\d{2}:\d{2}", container.get_text()):
                break
        text = container.get_text(" ", strip=True) if container else ""

        # "Ready or not 2 söndag 29 mars 19:00 Läs mer >>"
        m = re.search(
            r"(.+?)\s+(?:måndag|tisdag|onsdag|torsdag|fredag|lördag|söndag)\s+"
            r"(\d{1,2})\s+(\w+)\s+(\d{1,2}):(\d{2})",
            text,
            re.IGNORECASE,
        )
        if not m:
            continue

        title = m.group(1).strip()
        day = int(m.group(2))
        month = _MONTHS.get(m.group(3).lower())
        hour, minute = int(m.group(4)), int(m.group(5))

        if not month or not title:
            continue

        key = (title, f"{month:02d}-{day:02d}")
        if key in seen:
            continue
        seen.add(key)

        tmdb_id = _tmdb(title)
        if tmdb_id is None:
            continue

        if not href.startswith("http"):
            href = "https://fhbracke.se" + href

        yield Screening(
            tmdb_id=tmdb_id,
            date=date(infer_year(month), month, day),
            time=time(hour, minute),
            ticket_url=href,
            cinema_name=_CINEMA,
            city=_CITY,
        )
