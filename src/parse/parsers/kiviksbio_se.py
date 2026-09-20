"""kiviksbio.se — WordPress Events Manager plugin."""

import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, time

import requests
from bs4 import BeautifulSoup, Tag

from parse._util import infer_year
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

_SOURCE = "kiviksbio_se"
_URL = "https://www.kiviksbio.se/evenemang/"
_CINEMA = "Kiviks Bio"
_CITY = "Kivik"
_ADDRESS = "Ordensgatan 5"

# The listing's only non-genre category.
_NOT_A_GENRE = {"film"}

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


def _runtime(start: time, end_text: str) -> int | None:
    """Minutes between the listed start and end times."""
    m = re.match(r"(\d{1,2}):(\d{2})", end_text)
    if not m:
        return None
    minutes = (int(m.group(1)) * 60 + int(m.group(2))) - (start.hour * 60 + start.minute)
    if minutes <= 0:
        minutes += 24 * 60
    return minutes


def _film(ev: Tag, title: str, url: str, runtime: int | None) -> Film:
    """Film metadata from an event item.

    No poster: the site carries only landscape banner art.
    """
    tags = ev.select_one(".em-event-tags")
    genres = [
        text
        for a in ev.select(".em-event-categories li")
        if (text := a.get_text(strip=True)) and text.lower() not in _NOT_A_GENRE
    ]
    return _films.make(
        _SOURCE,
        title,
        runtime=runtime,
        genres=genres,
        age_rating=" ".join(tags.get_text().split()) if tags else "",
        url=url,
    )


def _overview(page: str) -> str:
    """Synopsis from an event page."""
    soup = BeautifulSoup(page, "html.parser")
    content = soup.select_one(".em-event-content")
    return " ".join(content.get_text(" ").split()) if content else ""


def _showtimes(page: str) -> Iterator[tuple[Film, date, time, str]]:
    """Yield (film, date, time, ticket_url) per event item."""
    soup = BeautifulSoup(page, "html.parser")

    for ev in soup.select(".em-item"):
        title_el = ev.select_one(".em-item-title a")
        date_el = ev.select_one(".em-event-date")
        if not title_el or not date_el:
            continue

        # Titles carry indentation runs that HTML rendering collapses.
        film_title = " ".join(title_el.get_text().split())
        ticket_url = title_el.get("href", "")

        # Parse "onsdag 1 apr kl 15:00 - 16:45"
        date_text = date_el.get_text(strip=True)
        m = re.match(r"\w+\s+(\d{1,2})\s+(\w+)\s+kl\s+(\d{1,2}):(\d{2})(?:\s*-\s*(\d{1,2}:\d{2}))?", date_text)
        if not m or not film_title or not ticket_url:
            continue

        day = int(m.group(1))
        month = _MONTHS.get(m.group(2))
        if not month:
            continue

        d = date(infer_year(month), month, day)
        t = time(int(m.group(3)), int(m.group(4)))

        yield _film(ev, film_title, ticket_url, _runtime(t, m.group(5) or "")), d, t, ticket_url


def parse() -> Iterator[Screening | Venue | Film]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    resp = session.get(_URL, timeout=15)
    resp.raise_for_status()

    seen: set[str] = set()
    for film, d, t, ticket_url in _showtimes(resp.text):
        if film.key not in seen:
            seen.add(film.key)
            detail = session.get(film.url, timeout=15)
            if detail.ok:
                film = replace(film, overview=_overview(detail.text))
            yield _films.register(film, session=session)

        yield Screening(
            tmdb_id=_tmdb(film.title),
            title=film.title,
            film_key=film.key,
            date=d,
            time=t,
            ticket_url=ticket_url,
            cinema_name=_CINEMA,
            city=_CITY,
        )
