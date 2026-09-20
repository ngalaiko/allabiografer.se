"""hallundafolketshus.se — CaféBio events with DD/MM HH:MM format."""

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

_URL = "https://www.hallundafolketshus.se/"
_CINEMA = "Hallunda Folkets Hus"
_CITY = "Norsborg"
_ADDRESS = "Borgvägen 1"
_SOURCE = "hallundafolketshus_se"

_HEADERS = {"User-Agent": "Mozilla/5.0"}

# Site chrome that shares the uploads directory with film posters.
_NOT_A_POSTER = re.compile(r"logo|favicon|icon", re.IGNORECASE)

_HOURS = re.compile(r"(\d+)\s*tim\w*(?:\s*(\d+)\s*min\w*)?", re.IGNORECASE)
_MINUTES = re.compile(r"^(\d+)\s*min\w*$", re.IGNORECASE)
_AGE = re.compile(r"^(barntillåten|(?:från|fr\.?)\s*\d+\s*år|\d+\s*år)$", re.IGNORECASE)


def _events(html: str) -> Iterator[tuple[str, date, time, str]]:
    """Yield (title, date, time, ticket_url) for every CaféBio event in *html*."""
    soup = BeautifulSoup(html, "html.parser")
    seen: set[tuple[str, str]] = set()

    for el in soup.select("[class*=event]"):
        text = el.get_text(" ", strip=True)
        if "CaféBio" not in text:
            continue

        # Containers wrapping several events aggregate their text and links.
        hrefs = {a.get("href", "") for a in el.find_all("a", href=re.compile(r"/events/"))}
        if len(hrefs) != 1:
            continue

        m = re.search(r"CaféBio\s+(.+?)\s+(\d{2})/(\d{2})\s+(\d{2}):(\d{2})", text)
        if not m:
            continue

        title = m.group(1).strip()
        day, month = int(m.group(2)), int(m.group(3))
        hour, minute = int(m.group(4)), int(m.group(5))

        href = next(iter(hrefs))
        if not href:
            continue
        if not href.startswith("http"):
            href = _URL.rstrip("/") + href

        key = (title, f"{day:02d}/{month:02d}")
        if key in seen:
            continue
        seen.add(key)

        yield title, date(infer_year(month), month, day), time(hour, minute), href


def _runtime(line: str) -> int | None:
    """Minutes from "1 timme 51 min" or "111 min"."""
    if m := _MINUTES.match(line):
        return int(m.group(1))
    if m := _HOURS.search(line):
        return int(m.group(1)) * 60 + int(m.group(2) or 0)
    return None


def _details(html: str) -> dict:
    """Poster, genres, runtime, age rating and synopsis from one event page."""
    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("article") or soup
    for tag in article(["script", "style"]):
        tag.decompose()

    poster_url = ""
    for img in article.find_all("img"):
        src = img.get("src", "")
        if "/uploads/" in src and not _NOT_A_POSTER.search(src):
            poster_url = src
            break

    # The film block is three bold lines — genres, length or age, director —
    # followed by the synopsis paragraph.
    paragraphs = article.find_all("p")
    details: dict = {"poster_url": poster_url, "genres": [], "runtime": None, "age_rating": "", "overview": ""}
    for i, p in enumerate(paragraphs):
        text = p.get_text("\n", strip=True)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if len(text) > 300 or not any(line.startswith("Regi:") for line in lines):
            continue

        if not lines[0].startswith("Regi:"):
            details["genres"] = [g.strip() for g in re.split(r"[,/]", lines[0]) if g.strip()]
        for line in lines[1:]:
            if _AGE.match(line):
                details["age_rating"] = line
            elif runtime := _runtime(line):
                details["runtime"] = runtime

        rest = (tail.get_text(" ", strip=True) for tail in paragraphs[i + 1 :])
        details["overview"] = next((t for t in rest if len(t) > 120), "")
        break

    return details


def _fetch(url: str) -> str:
    resp = requests.get(url, timeout=15, headers=_HEADERS)
    resp.raise_for_status()
    return resp.text


def parse() -> Iterator[Screening | Venue | Film]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)

    seen: set[str] = set()
    for title, day, start, href in _events(_fetch(_URL)):
        if title not in seen:
            seen.add(title)
            details = {}
            try:
                details = _details(_fetch(href))
            except requests.RequestException as exc:
                log.warning("hallundafolketshus: %s details failed: %s", href, exc)
            yield _films.register(_films.make(_SOURCE, title, url=href, **details))

        yield Screening(
            tmdb_id=_tmdb(title),
            film_key=film_key(_SOURCE, title),
            title=title,
            date=day,
            time=start,
            ticket_url=href,
            cinema_name=_CINEMA,
            city=_CITY,
        )
