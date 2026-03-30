"""hallundafolketshus.se — CaféBio events with DD/MM HH:MM format."""

import re
from collections.abc import Iterator
from datetime import date, time

import requests
from bs4 import BeautifulSoup

from parse._util import infer_year
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Screening, Venue

_URL = "https://www.hallundafolketshus.se/"
_CINEMA = "Hallunda Folkets Hus"
_CITY = "Norsborg"
_ADDRESS = "Borgvägen 1"


def parse() -> Iterator[Screening | Venue]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)
    resp = requests.get(_URL, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    seen: set[tuple[str, str]] = set()

    for el in soup.select("[class*=event]"):
        text = el.get_text(" ", strip=True)
        if "CaféBio" not in text:
            continue

        m = re.search(r"CaféBio\s+(.+?)\s+(\d{2})/(\d{2})\s+(\d{2}):(\d{2})", text)
        if not m:
            continue

        title = m.group(1).strip()
        day, month = int(m.group(2)), int(m.group(3))
        hour, minute = int(m.group(4)), int(m.group(5))

        link = el.find("a", href=re.compile(r"/events/"))
        href = link.get("href", "") if link else ""
        if not href:
            continue
        if not href.startswith("http"):
            href = _URL.rstrip("/") + href

        key = (title, f"{day:02d}/{month:02d}")
        if key in seen:
            continue
        seen.add(key)

        tmdb_id = _tmdb(title)
        if tmdb_id is None:
            continue

        yield Screening(
            tmdb_id=tmdb_id,
            date=date(infer_year(month), month, day),
            time=time(hour, minute),
            ticket_url=href,
            cinema_name=_CINEMA,
            city=_CITY,
        )
