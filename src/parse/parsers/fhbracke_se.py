"""fhbracke.se — Bräcke Bio, WordPress with "Title weekday DD month HH:MM" format."""

import logging
import re
from collections.abc import Iterator
from datetime import date, time

import requests
from bs4 import BeautifulSoup

from parse._util import infer_year
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue, film_key

log = logging.getLogger(__name__)

_URL = "https://fhbracke.se/bio/"
_BASE = "https://fhbracke.se"
_CINEMA = "Bräcke Bio"
_CITY = "Bräcke"
_ADDRESS = "Hantverksgatan 27"
_SOURCE = "fhbracke_se"

_HEADERS = {"User-Agent": "Mozilla/5.0"}

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

_SHOWTIME = re.compile(
    r"(.+?)\s+(?:måndag|tisdag|onsdag|torsdag|fredag|lördag|söndag)\s+(\d{1,2})\s+(\w+)\s+(\d{1,2}):(\d{2})",
    re.IGNORECASE,
)

# Site chrome that shares the uploads directory with film posters.
_NOT_A_POSTER = re.compile(r"logo|favicon|icon|brackebio|BrackeFH", re.IGNORECASE)

_RUNTIME = re.compile(r"Speltid:\s*(\d+)", re.IGNORECASE)
_AGE = re.compile(r"Åldersgräns:\s*(.+)", re.IGNORECASE)


def _absolute(href: str) -> str:
    return href if href.startswith("http") else _BASE + href


def _listings(html: str) -> Iterator[dict]:
    """Yield one dict per showtime on the programme page: title, date, time, url, poster."""
    soup = BeautifulSoup(html, "html.parser")
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
        m = _SHOWTIME.search(text)
        if not m:
            continue

        title = m.group(1).strip()
        day = int(m.group(2))
        month = _MONTHS.get(m.group(3).lower())
        hour, minute = int(m.group(4)), int(m.group(5))

        if not month or not title or not href:
            continue

        key = (title, f"{month:02d}-{day:02d}")
        if key in seen:
            continue
        seen.add(key)

        poster = next(
            (
                src
                for img in container.find_all("img")
                if (src := img.get("src", "")) and "/uploads/" in src and not _NOT_A_POSTER.search(src)
            ),
            "",
        )

        yield {
            "title": title,
            "date": date(infer_year(month), month, day),
            "time": time(hour, minute),
            "url": _absolute(href),
            "poster_url": poster,
        }


def _details(html: str) -> dict:
    """Synopsis, runtime and age rating from one film page."""
    soup = BeautifulSoup(html, "html.parser")
    details: dict = {"overview": "", "runtime": None, "age_rating": ""}

    facts = [span.get_text(" ", strip=True) for span in soup.select("span.elementor-icon-list-text")]
    for fact in facts:
        if m := _RUNTIME.search(fact):
            details["runtime"] = int(m.group(1))
        elif m := _AGE.search(fact):
            details["age_rating"] = m.group(1).strip()

    # The synopsis shares a top-level section with the fact list.
    anchor = next((s for s in soup.select("span.elementor-icon-list-text") if "Åldersgräns" in s.get_text()), None)
    section = anchor.find_parent(class_="elementor-top-section") if anchor else None
    editors = (section or soup).select(".elementor-widget-text-editor")
    if editors:
        details["overview"] = editors[0].get_text("\n", strip=True)

    return details


def _fetch(url: str) -> str:
    resp = requests.get(url, timeout=15, headers=_HEADERS)
    resp.raise_for_status()
    return resp.text


def parse() -> Iterator[Screening | Venue | Film]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)

    seen: set[str] = set()
    for show in _listings(_fetch(_URL)):
        title = show["title"]
        if title not in seen:
            seen.add(title)
            details = {}
            try:
                details = _details(_fetch(show["url"]))
            except requests.RequestException as exc:
                log.warning("fhbracke: %s details failed: %s", show["url"], exc)
            yield _films.register(
                _films.make(_SOURCE, title, url=show["url"], poster_url=show["poster_url"], **details)
            )

        yield Screening(
            tmdb_id=_tmdb(title),
            film_key=film_key(_SOURCE, title),
            title=title,
            date=show["date"],
            time=show["time"],
            ticket_url=show["url"],
            cinema_name=_CINEMA,
            city=_CITY,
        )
