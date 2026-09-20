"""palladiumbio.se — Filmhuset Palladium, Arvika."""

import logging
import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, time

import requests
from bs4 import BeautifulSoup

from parse._util import infer_year
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

log = logging.getLogger(__name__)

_SOURCE = "palladiumbio_se"
_URL = "https://palladiumbio.se/"
_CINEMA = "Filmhuset Palladium"
_CITY = "Arvika"
_ADDRESS = "Hamngatan 11"

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


def _parse_title(raw: str) -> tuple[str, str, str]:
    """Extract (film_title, language, subtitles) from a raw title string.

    Examples:
        "Super Mario Galaxy Filmen  (Tal: Eng) (Text: Sv)"
        "Köln 75  (Tal: Tyska) (Text: Svenska)"
        "Super Mario Galaxy Filmen  (Tal: Svenska (dubbat))"
        "BIODLAREN (Tal:Sv) (Tex:Sv)"
        "Practical Magic: Family Legacy  (Tal: Eng)(Txt:Sv)"
    """
    language = ""
    subtitles = ""

    # Extract language — handles both "Tal: Eng" and "Tal:Sv" and "Tal: Svenska (dubbat)"
    m = re.search(r"\(Tal:\s*((?:[^()]*|\([^)]*\))*)\)", raw)
    if m:
        language = m.group(1).strip()

    # Extract subtitles — handles "Text: Sv", "Tex:Sv", "Txt:Sv", "Text: Svenska"
    m = re.search(r"\(T(?:ext|ex|xt):\s*([^)]+)\)", raw)
    if m:
        subtitles = m.group(1).strip()

    # Strip everything from first parenthesis for the title
    title = re.sub(r"\s*\(.*", "", raw).strip()

    return title, language, subtitles


def _parse_screen(venue_text: str) -> str:
    """Extract screen name from venue text like 'Filmhuset Palladium Arvika, Salong 2'."""
    m = re.search(r",\s*(Salong\s+\S+)", venue_text)
    return m.group(1) if m else ""


def _overview(page: str) -> str:
    """Synopsis from a film page; the paragraphs precede the showings table."""
    soup = BeautifulSoup(page, "html.parser")
    return " ".join(" ".join(p.get_text(" ") for p in soup.select("main .lead > p")).split())


def _showtimes(html: str) -> Iterator[tuple[Film, date, time, str, str, str, str]]:
    """Yield (film, date, time, ticket_url, screen, language, subtitles) per program row."""
    soup = BeautifulSoup(html, "html.parser")

    current_date: date | None = None

    for tr in soup.select("table.tableBioprogram tr"):
        # Date header row
        th = tr.select_one("th.date")
        if th:
            text = th.get_text(strip=True)
            # "Onsdag 1 april"
            m = re.match(r"\w+\s+(\d{1,2})\s+(\w+)", text)
            if m:
                day = int(m.group(1))
                month = _MONTHS.get(m.group(2).lower())
                if month:
                    current_date = date(infer_year(month), month, day)
            continue

        if current_date is None:
            continue

        time_el = tr.select_one("td.time span")
        title_el = tr.select_one("td.title a")
        venue_el = tr.select_one("td.venue")
        buy_el = tr.select_one("td.buy a.btn-primary")

        if not time_el or not title_el or not buy_el:
            continue

        raw_time = time_el.get_text(strip=True)
        m = re.match(r"(\d{1,2}):(\d{2})", raw_time)
        if not m:
            continue
        t = time(int(m.group(1)), int(m.group(2)))

        raw_title = title_el.get_text(strip=True)
        film_title, language, subtitles = _parse_title(raw_title)
        if not film_title:
            continue

        ticket_url = buy_el.get("href", "")
        if not ticket_url:
            continue

        screen = _parse_screen(venue_el.get_text(strip=True)) if venue_el else ""

        # Every showing is its own event; its page carries the film's synopsis.
        film = _films.make(_SOURCE, film_title, url=title_el.get("href", ""))

        yield film, current_date, t, ticket_url, screen, language, subtitles


def parse() -> Iterator[Screening | Venue | Film]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    resp = session.get(_URL, timeout=15)
    resp.raise_for_status()

    count = 0
    seen: set[str] = set()
    for film, d, t, ticket_url, screen, language, subtitles in _showtimes(resp.text):
        if film.key not in seen:
            seen.add(film.key)
            if film.url:
                detail = session.get(film.url, timeout=15)
                if detail.ok:
                    film = replace(film, overview=_overview(detail.text))
            yield film
        yield Screening(
            tmdb_id=_tmdb(film.title),
            title=film.title,
            film_key=film.key,
            date=d,
            time=t,
            ticket_url=ticket_url,
            cinema_name=_CINEMA,
            city=_CITY,
            screen=screen,
            language=language,
            subtitles=subtitles,
        )
        count += 1

    log.info("palladiumbio.se: %d screenings", count)
