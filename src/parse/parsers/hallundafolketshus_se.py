"""hallundafolketshus.se — CaféBio, film and opera events; tickets per showing on Tickster."""

import logging
import re
from collections.abc import Iterator
from datetime import date, time

import requests
from bs4 import BeautifulSoup

from parse import _http, _version
from parse._util import infer_year
from parse.parsers import _films, _tickster
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue, film_key

log = logging.getLogger(__name__)

_URL = "https://www.hallundafolketshus.se/"
_CINEMA = "Hallunda Folkets Hus"
_CITY = "Norsborg"
_ADDRESS = "Borgvägen 1"
_SOURCE = "hallundafolketshus_se"

_SESSION = _http.session("Mozilla/5.0")

# Site chrome that shares the uploads directory with film posters.
_NOT_A_POSTER = re.compile(r"logo|favicon|icon", re.IGNORECASE)

# Event categories that are screenings: "CaféBio", "Film", "Opera - Live på Bio".
_SCREENING = re.compile(r"bio|^film$", re.IGNORECASE)
_WHEN = re.compile(r"^(\d{2})/(\d{2})\s+(\d{2}):(\d{2})")

_HOURS = re.compile(r"(\d+)\s*tim\w*(?:\s*(?:och\s*)?(\d+)\s*min\w*)?", re.IGNORECASE)
_MINUTES = re.compile(r"^(\d+)\s*min\w*$", re.IGNORECASE)
_AGE = re.compile(r"^(barntillåten|(?:från|fr\.?)\s*\d+\s*år|\d+\s*år)$", re.IGNORECASE)

# Labelled fact paragraphs: "Längd: 1 tim 22 min", "Speltid Cirka 3 timmar och 29 minuter", "Språk Italienska".
_LABELLED = re.compile(r"^(Speltid|Längd|Genre|Språk)\s*:?\s*(.+)$", re.IGNORECASE)
_SUBTITLED = re.compile(r"^(\w+)\s+undertext", re.IGNORECASE)


def _text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split()) if el else ""


def _title(raw: str) -> str:
    """Film and opera titles are set in capitals: "MACBETH" becomes "Macbeth"."""
    title = " ".join(raw.split())
    return title.capitalize() if title.isupper() else title


def _events(html: str) -> Iterator[tuple[str, date, time, str]]:
    """Yield (title, date, time, event_url) for every screening event in *html*."""
    soup = BeautifulSoup(html, "html.parser")
    seen: set[tuple[str, date]] = set()

    for item in soup.select(".em-event.em-item"):
        if not _SCREENING.search(_text(item.select_one(".em-item-cat"))):
            continue
        link = item.select_one(".em-item-title a[href]")
        m = _WHEN.match(_text(item.select_one(".em-date-time")))
        if not link or not m:
            continue

        title = _title(_text(link))
        day, month = int(m.group(1)), int(m.group(2))
        when = date(infer_year(month), month, day)
        href = link["href"]
        if not title or (title, when) in seen:
            continue
        seen.add((title, when))
        if not href.startswith("http"):
            href = _URL.rstrip("/") + href

        yield title, when, time(int(m.group(3)), int(m.group(4))), href


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

    # Film and opera pages label each fact instead.
    for label, value in _labelled(article):
        if label in ("speltid", "längd") and not details["runtime"]:
            details["runtime"] = _runtime(value)
        elif label == "genre" and not details["genres"]:
            details["genres"] = [g.strip() for g in re.split(r"[,/]", value) if g.strip()]
    if not details["overview"]:
        # Unclosed tags can leave a paragraph wrapping the rest of the page.
        details["overview"] = next((t for p in paragraphs if not p.find("p") and len(t := _text(p)) > 120), "")

    return details


def _labelled(article) -> Iterator[tuple[str, str]]:
    for p in article.find_all("p"):
        if m := _LABELLED.match(_text(p)):
            yield m.group(1).lower(), m.group(2)


def _stated_version(html: str) -> tuple[str, str]:
    """(language, subtitles) from "Språk Italienska" and "Svenska undertexter!"."""
    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("article") or soup
    language = next((_version.language(v) for label, v in _labelled(article) if label == "språk"), "")
    subtitles = next(
        (_version.subtitles(m.group(1)) for p in article.find_all("p") if (m := _SUBTITLED.match(_text(p)))), ""
    )
    return language, subtitles


def _ticket(html: str) -> str:
    """The "Köp Biljett" Tickster link on an event page."""
    soup = BeautifulSoup(html, "html.parser")
    link = soup.select_one("a[href*='tickster.com']")
    return link["href"] if link else ""


def _screen(venue: str) -> str:
    """ "Hallunda Folkets Hus - Brage" names the Brage salon."""
    return venue.removeprefix(_CINEMA).strip(" -")


def _fetch(url: str) -> str:
    resp = _SESSION.get(url, timeout=15)
    resp.raise_for_status()
    return resp.text


def parse() -> Iterator[Screening | Venue | Film]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)

    seen: set[str] = set()
    for title, day, start, href in _events(_fetch(_URL)):
        page = ""
        try:
            page = _fetch(href)
        except requests.RequestException as exc:
            log.warning("hallundafolketshus: %s failed: %s", href, exc)

        if title not in seen:
            seen.add(title)
            details = _details(page) if page else {}
            yield _films.register(_films.make(_SOURCE, title, url=href, **details))

        ticket = _ticket(page) if page else ""
        event = _tickster.fetch_event(ticket, _SESSION) if ticket else None
        language, subtitles = _stated_version(page) if page else ("", "")
        if event:
            _, spoken, subs = _tickster.version(event.title)
            language, subtitles = spoken or language, subs or subtitles

        yield Screening(
            tmdb_id=_tmdb(title),
            film_key=film_key(_SOURCE, title),
            title=title,
            date=day,
            time=start,
            ticket_url=event.url if event else ticket or href,
            cinema_name=_CINEMA,
            city=_CITY,
            screen=_screen(event.venue) if event else "",
            **_version.screening_facts(language=language, subtitles=subtitles),
        )
