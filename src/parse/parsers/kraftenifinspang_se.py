"""Free film screenings in Kraften i Finspång's public local calendar."""

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from html import unescape
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from parse import _http, _version
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

_SOURCE = "kraftenifinspang_se"
_URL = "https://kraftenifinspang.se/wp-json/tribe/events/v1/events"
_TZ = ZoneInfo("Europe/Stockholm")
_FREE = re.compile(r"^(?:fri entr[eé]|gratis|kostnadsfri(?:tt)?|0(?:[.,]0+)?\s*(?:kr|sek)?)\s*!?$", re.IGNORECASE)
_PREFIX = re.compile(r"^(?:Knattebio|Barnbio|Familjebio|Dagbio|Bio)\s*:\s*", re.IGNORECASE)
_SUFFIX = re.compile(r"\s+[-–—]\s*(?:fri entr[eé]|gratis)\s*!?$", re.IGNORECASE)
_TICKSTER = re.compile(r"https?://(?:[\w-]+\.)?tickster\.com/", re.IGNORECASE)


def parse() -> Iterator[Screening | Venue | Film]:
    session = _http.session()
    today = datetime.now(_TZ).date()
    page = 1
    seen: set[tuple] = set()
    films: set[str] = set()
    venues: set[tuple[str, str]] = set()
    while True:
        response = session.get(_URL, params={"start_date": today.isoformat(), "per_page": 50, "page": page}, timeout=30)
        response.raise_for_status()
        data = response.json()
        for event in data["events"]:
            fields = event.get("custom_fields") or {}
            if not any("Film/Bio" in field["value"].split("|") for field in fields.values()):
                continue
            # A missing price is unknown, not free; paid listings belong to Tickster.
            if not _FREE.fullmatch(unescape(event.get("cost", "")).strip()) or event.get("all_day"):
                continue
            description = BeautifulSoup(event.get("description", ""), "html.parser")
            if _TICKSTER.match(unescape(event.get("website", ""))) or description.find("a", href=_TICKSTER):
                continue
            venue = event.get("venue") or {}
            name, city = venue.get("venue", "").strip(), venue.get("city", "").strip()
            if not name or not city:
                continue
            # The API supplies UTC separately; convert it before taking the local date and time.
            start = datetime.fromisoformat(event["utc_start_date"]).replace(tzinfo=UTC).astimezone(_TZ)
            if start.date() < today:
                continue
            raw = _SUFFIX.sub("", _PREFIX.sub("", unescape(event["title"]))).strip()
            title, fmt, language, subtitles = _version.split_title(raw)
            film = _films.make(_SOURCE, title, url=event["url"], overview=description.get_text(" ", strip=True))
            key = (city, name, film.key, start)
            if key in seen:
                continue
            seen.add(key)
            if (city, name) not in venues:
                venues.add((city, name))
                yield Venue(name=name, city=city, address=venue.get("address", ""))
            if film.key not in films:
                films.add(film.key)
                yield film
            yield Screening(
                title=title,
                film_key=film.key,
                tmdb_id=_tmdb(title),
                date=start.date(),
                time=start.time(),
                cinema_name=name,
                city=city,
                ticket_url=event["url"],
                **_version.screening_facts(
                    format=fmt, language=language, subtitles=subtitles, raw_attributes=("Fri entré",)
                ),
            )
        if page >= data["total_pages"]:
            break
        page += 1
