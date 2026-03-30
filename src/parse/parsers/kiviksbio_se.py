"""kiviksbio.se — WordPress Events Manager plugin."""

import re
from collections.abc import Iterator
from datetime import date, time

import requests
from bs4 import BeautifulSoup

from parse._util import infer_year
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Screening, Venue

_URL = "https://www.kiviksbio.se/evenemang/"
_CINEMA = "Kiviks Bio"
_CITY = "Kivik"
_ADDRESS = "Ordensgatan 5"

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "maj": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "okt": 10,
    "nov": 11,
    "dec": 12,
}


def parse() -> Iterator[Screening | Venue]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)
    resp = requests.get(_URL, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    for ev in soup.select(".em-item"):
        title_el = ev.select_one(".em-item-title a")
        date_el = ev.select_one(".em-event-date")
        if not title_el or not date_el:
            continue

        film_title = title_el.get_text(strip=True)
        # Strip common prefixes like "Påsklovsfilm!" or "Favorit i repris!"
        film_title = re.sub(r"^[^!]+!\s*", "", film_title).strip()
        ticket_url = title_el.get("href", "")

        # Parse "onsdag 1 apr kl 15:00 - 16:45"
        date_text = date_el.get_text(strip=True)
        m = re.match(r"\w+\s+(\d{1,2})\s+(\w+)\s+kl\s+(\d{1,2}):(\d{2})", date_text)
        if not m or not film_title or not ticket_url:
            continue

        day = int(m.group(1))
        month = _MONTHS.get(m.group(2))
        if not month:
            continue

        d = date(infer_year(month), month, day)
        t = time(int(m.group(3)), int(m.group(4)))

        tmdb_id = _tmdb(film_title)
        if tmdb_id is None:
            continue

        yield Screening(
            tmdb_id=tmdb_id,
            date=d,
            time=t,
            ticket_url=ticket_url,
            cinema_name=_CINEMA,
            city=_CITY,
        )
