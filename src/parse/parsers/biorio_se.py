"""biorio.se — Next.js calendar page, rendered client-side via Playwright."""

import logging
import re
from collections.abc import Iterator
from datetime import date, time
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from parse._util import infer_year
from parse.parsers import _films
from parse.parsers._browser import page as browser_page
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

log = logging.getLogger(__name__)

_SOURCE = "biorio_se"
_URL = "https://www.biorio.se/sv/kalender"
_CINEMA = "Bio Rio"
_CITY = "Stockholm"
_ADDRESS = "Hornstulls strand 3"

# The site serves posters through Next.js' image proxy; its width is ours to pick.
_POSTER_WIDTH = "640"

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


def _parse_date(text: str) -> date | None:
    """Parse 'Idag 31 mars', 'Imorgon 1 april', 'Fredag 3 april', etc."""
    m = re.search(r"(\d{1,2})\s+(\w+)", text)
    if not m:
        return None
    day = int(m.group(1))
    month = _MONTHS.get(m.group(2).lower())
    if not month:
        return None
    return date(infer_year(month), month, day)


def _showtimes(html: str) -> Iterator[tuple[str, date, time, str, str]]:
    """Yield (title, date, time, ticket_url, screen) from the rendered calendar.

    Each day group holds a date header and a list of showtime items.  The
    booking link wraps only the poster; time, title and screen live beside it
    in the item's info block.
    """
    soup = BeautifulSoup(html, "html.parser")

    for group in soup.select(".kalender-day-group"):
        header = group.select_one(".kalender-date-header")
        d = _parse_date(header.get_text(strip=True)) if header else None
        if not d:
            continue

        for item in group.select(".kalender-showtime-item"):
            link = item.select_one('a[href*="/boka/"]')
            title_el = item.select_one(".kalender-showtime-title")
            time_el = item.select_one(".kalender-showtime-time")
            if not link or not title_el or not time_el:
                continue

            m = re.match(r"(\d{1,2}):(\d{2})", time_el.get_text(strip=True))
            if not m:
                continue

            title = title_el.get_text(strip=True)
            if not title:
                continue

            meta = item.select_one(".kalender-showtime-meta")
            screen_m = re.search(r"Salong\s*\d+", meta.get_text(" ", strip=True)) if meta else None

            yield (
                title,
                d,
                time(int(m.group(1)), int(m.group(2))),
                urljoin(_URL, link.get("href", "")),
                screen_m.group(0) if screen_m else "",
            )


def _film_urls(html: str) -> dict[str, str]:
    """Map each calendar title to its film page; the title itself links there."""
    soup = BeautifulSoup(html, "html.parser")
    urls: dict[str, str] = {}
    for link in soup.select(".kalender-showtime-title[href]"):
        title = link.get_text(strip=True)
        if title:
            urls.setdefault(title, urljoin(_URL, link["href"]))
    return urls


def _film_details(html: str) -> dict:
    """Poster, synopsis, runtime, genres and year from a film page."""
    soup = BeautifulSoup(html, "html.parser")

    credits = {}
    for item in soup.select(".movie-credit-item"):
        label = item.select_one(".movie-credit-label")
        value = item.select_one(".movie-credit-value")
        if label and value:
            credits[label.get_text(strip=True).casefold()] = value.get_text(" ", strip=True)

    genres = [g.strip() for g in credits.get("genre", "").split(",") if g.strip()]

    synopsis = soup.select_one(".movie-synopsis-text")
    poster = soup.select_one("img.movie-poster-img")

    return {
        "poster_url": _poster_url(poster.get("src", "")) if poster else "",
        "overview": synopsis.get_text(" ", strip=True) if synopsis else "",
        "runtime": _runtime(credits.get("längd", "")),
        "genres": genres,
        "release_date": _year(soup),
    }


def _poster_url(src: str) -> str:
    """Absolute poster URL, widened from the thumbnail the page asks for."""
    if not src:
        return ""
    parts = urlparse(urljoin(_URL, src))
    if not parts.path.startswith("/_next/image"):
        return parts.geturl()
    query = dict(parse_qsl(parts.query))
    query["w"] = _POSTER_WIDTH
    return urlunparse(parts._replace(query=urlencode(query)))


def _runtime(text: str) -> int | None:
    """Minutes from '1h 38min' or '98 min'."""
    m = re.search(r"(?:(\d+)\s*h)?\s*(\d+)\s*min", text)
    if not m:
        return None
    return int(m.group(1) or 0) * 60 + int(m.group(2))


def _year(soup: BeautifulSoup) -> str:
    """The 'ÅR' cell of the meta grid — the site gives a year, never a full date."""
    grid = soup.select_one(".movie-meta-grid")
    if not grid:
        return ""
    labels = [el.get_text(strip=True).casefold() for el in grid.select(".movie-meta-label")]
    values = [el.get_text(strip=True) for el in grid.select(".movie-meta-value")]
    if "år" not in labels:
        return ""
    value = values[labels.index("år")] if labels.index("år") < len(values) else ""
    return value if re.fullmatch(r"\d{4}", value) else ""


def parse() -> Iterator[Screening | Venue | Film]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)

    with browser_page() as page:
        page.goto(_URL, wait_until="networkidle", timeout=30000)
        html = page.content()

    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; bio-parser/1.0)"

    films: dict[str, Film] = {}
    for title, url in _film_urls(html).items():
        films[title] = _films.register(_films.make(_SOURCE, title, url=url, **_details(session, url)), session=session)
        yield films[title]

    for title, d, t, ticket_url, screen in _showtimes(html):
        film = films.get(title)
        yield Screening(
            tmdb_id=_tmdb(title),
            title=title,
            date=d,
            time=t,
            ticket_url=ticket_url,
            cinema_name=_CINEMA,
            city=_CITY,
            screen=screen,
            film_key=film.key if film else "",
        )


def _details(session: requests.Session, url: str) -> dict:
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("biorio.se: film page %s failed: %s", url, exc)
        return {}
    return _film_details(resp.text)
