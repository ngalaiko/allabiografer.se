"""osbyborgen.se — Tickster Vue.js with vueData_sessions JSON in HTML."""

import json
import re
from collections.abc import Iterator
from datetime import date, time

import requests

from parse._util import infer_year
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Screening, Venue

_URL = "https://osbyborgen.se/"
_CINEMA = "Bio Borgen"
_CITY = "Osby"
_ADDRESS = "Västra Storgatan"

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


def _parse_date(text: str) -> date | None:
    m = re.match(r"\w+\s+(\d{1,2})\s+(\w+)", text.strip().lower())
    if not m:
        return None
    day, mon = int(m.group(1)), _MONTHS.get(m.group(2))
    return date(infer_year(mon), mon, day) if mon else None


def _parse_time(text: str) -> time | None:
    m = re.match(r"(\d{1,2}):(\d{2})", text.strip())
    return time(int(m.group(1)), int(m.group(2))) if m else None


def parse() -> Iterator[Screening | Venue]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)
    resp = requests.get(_URL, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    m = re.search(r'vueData_sessions\s*=\s*(\{.*?"sessions":\[.*?\]\})', resp.text, re.DOTALL)
    if not m:
        return
    data = json.loads(m.group(1))

    for sess in data.get("sessions", []):
        film_title = sess.get("f_title", "")
        t = _parse_time(sess.get("f_time", ""))
        d = _parse_date(sess.get("f_date", ""))
        ticket_url = sess.get("f_href", "")
        if not film_title or not t or not d or not ticket_url:
            continue
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
