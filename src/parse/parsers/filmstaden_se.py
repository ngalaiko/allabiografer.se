"""filmstaden.se — cinema-api.com REST API, all cinemas in one pass."""

import logging
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from curl_cffi import requests as cffi_requests

from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Screening, Venue

log = logging.getLogger(__name__)

_API = "https://services.cinema-api.com"


def _get(session: cffi_requests.Session, url: str, **kw: Any) -> Any:
    resp = session.get(url, impersonate="chrome", timeout=30, **kw)
    resp.raise_for_status()
    return resp.json()


def parse() -> Iterator[Screening]:
    session = cffi_requests.Session()
    cinemas = _get(session, f"{_API}/cinema/sv/1/1024").get("items", [])
    log.info("filmstaden: %d cinemas", len(cinemas))

    for cinema in cinemas:
        ncg_id = cinema["ncgId"]
        title = cinema["title"]
        addr = cinema.get("address", {})
        city = addr.get("city", {}).get("name", "Unknown")
        street = addr.get("streetAddress", "")

        yield Venue(name=title, city=city, address=street)

        page, shows = 1, []
        while True:
            data = _get(session, f"{_API}/show/sv/{page}/1024", params={"CinemaNcgId": ncg_id})
            items = data.get("items", [])
            shows.extend(items)
            if len(shows) >= data.get("totalNbrOfItems", 0) or len(items) < 1024:
                break
            page += 1

        count = 0
        for show in shows:
            raw = show.get("time", "")
            movie = show.get("movie", {})
            film_title = movie.get("title", "")
            if not raw or not film_title:
                continue
            tmdb_id = _tmdb(film_title)
            if tmdb_id is None:
                continue
            dt = datetime.fromisoformat(raw)
            attrs = show.get("attributes", [])
            yield Screening(
                tmdb_id=tmdb_id,
                date=dt.date(),
                time=dt.time(),
                cinema_name=title,
                city=city,
                screen=show.get("screen", {}).get("title", ""),
                format=", ".join(a["displayName"] for a in attrs if a.get("displayName")),
                ticket_url=f"https://www.filmstaden.se/bokning/kop/{show.get('remoteEntityId', '')}/",
            )
            count += 1

        log.info("  %s (%s): %d screenings", title, city, count)
