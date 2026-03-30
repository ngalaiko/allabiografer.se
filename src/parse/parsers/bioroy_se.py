"""bioroy.se — Next.js with __NEXT_DATA__ JSON containing full schedule."""

import json
import logging
import re
from collections.abc import Iterator
from datetime import datetime

import requests

from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Screening, Venue

log = logging.getLogger(__name__)

_URL = "https://www.bioroy.se/"
_CINEMA = "Bio Roy"
_CITY = "Göteborg"
_ADDRESS = "Kungsportsavenyen 45"


def parse() -> Iterator[Screening | Venue]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; bio-parser/1.0)"

    resp = session.get(_URL, timeout=30)
    resp.raise_for_status()

    m = re.search(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
    if not m:
        log.warning("bioroy.se: no JSON data found")
        return

    data = json.loads(m.group(1))
    pl = data.get("props", {}).get("pageProps", {}).get("programList", {})

    features = {f["id"]: f["info"]["title"] for f in pl.get("features", []) if f.get("info", {}).get("title")}

    count = 0
    for entry in pl.get("schedule", []):
        film_title = features.get(entry.get("featureId"), "")
        if not film_title:
            continue
        tmdb_id = _tmdb(film_title)
        if tmdb_id is None:
            continue

        for show in entry.get("dates", []):
            raw = show.get("startDate", "")
            ticket_url = show.get("ticksterLink", "")
            if not raw or not ticket_url:
                continue
            if show.get("soldOut"):
                continue

            dt = datetime.fromisoformat(raw.rstrip("Z"))
            screen = show.get("saloonLabel", "")

            yield Screening(
                tmdb_id=tmdb_id,
                date=dt.date(),
                time=dt.time(),
                ticket_url=ticket_url,
                cinema_name=_CINEMA,
                city=_CITY,
                screen=screen,
            )
            count += 1

    log.info("bioroy.se: %d screenings", count)
