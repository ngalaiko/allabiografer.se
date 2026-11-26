"""fhbracke.se — Bräcke Bio, WordPress with "Title weekday DD month HH:MM" format."""

import logging
import re
from datetime import date, time
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

from allabiografer.dates import infer_year

if TYPE_CHECKING:
    from collections.abc import Iterator

log = logging.getLogger(__name__)

_URL = "https://fhbracke.se/bio/"
_BASE = "https://fhbracke.se"
_EVENTS = "https://fhbracke.se/event/"
_CINEMA = "Bräcke Bio"
_CITY = "Bräcke"
_ADDRESS = "Hantverksgatan 27"
# The site links a Tickster search; the organiser page lists one event per showing.
_TICKSTER = "https://www.tickster.com/se/sv/events/by/g3vj0dntt6711k6/bracke-folkets-hus"


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
# Marks block boundaries; source newlines are formatting whitespace.
_BREAK = "\u2029"
# Event page date line: "Lördagen den 24 april 2027 kl. 19:00", "Lördagen den 5 december kl. 18:00".
_EVENT_WHEN = re.compile(r"(\d{1,2})\s+([a-zåäö]+)(?:\s+\d{4})?\s+kl\.?\s*(\d{1,2})[:.](\d{2})", re.IGNORECASE)
# Event pages that describe a cinema broadcast rather than a stage show.
_BROADCAST = re.compile(r"\bopera|metropolitan|\bmet-|livesänds|live på bio", re.IGNORECASE)
# Broadcast date sentences: "Upplev den live på bio 5 december 2026.", "Otello livesänds …, 24 april 2027."
_BROADCAST_DATE = re.compile(r"\s*[^.!?]*\b(?:live på bio|livesänds)\b[^.!?]*\b\d{4}\.", re.IGNORECASE)
# Tickster title suffixes naming the programme rather than the work: "Tosca - Favorit i repris".
_PROGRAMME_SUFFIX = re.compile(r"\s+[-–]\s+(Favorit i repris|Live på bio[^()]*)$", re.IGNORECASE)
_AGE = re.compile(r"Åldersgräns:\s*(.+)", re.IGNORECASE)


def _absolute(href: str) -> str:
    return href if href.startswith("http") else _BASE + href


def _poster(img) -> str:
    """Widest ``srcset`` candidate, else ``src``."""
    candidates = []
    for entry in (img.get("srcset") or "").split(","):
        parts = entry.split()
        if len(parts) == 2 and parts[1].endswith("w") and parts[1][:-1].isdigit():
            candidates.append((int(parts[1][:-1]), parts[0]))
    return max(candidates)[1] if candidates else img.get("src", "")


def _listings(html: str, *, year_for_month=infer_year) -> Iterator[dict]:
    """Yield one dict per showtime on the programme page: title, date, time, url, poster."""
    soup = BeautifulSoup(html, "html.parser")
    seen: set[tuple[str, int, int, int, int]] = set()

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

        key = (title, month, day, hour, minute)
        if key in seen:
            continue
        seen.add(key)
        try:
            when = date(year_for_month(month), month, day)
        except ValueError:
            log.warning("fhbracke: bad date %s %s for %r", m.group(2), m.group(3), title)
            continue

        poster = next(
            (
                _poster(img)
                for img in container.find_all("img")
                if (src := img.get("src", "")) and "/uploads/" in src and not _NOT_A_POSTER.search(src)
            ),
            "",
        )

        yield {
            "title": title,
            "date": when,
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
        details["overview"] = _paragraphs(editors[0])

    return details


def _paragraphs(el) -> str:
    """Text of *el*, one paragraph per block element or blank-line run, separated by blank lines."""
    for br in el.find_all("br"):
        br.replace_with("\n")
    for block in el.find_all(["p", "div", "li"]):
        block.insert_before(_BREAK)
        block.insert_after(_BREAK)
    parts = re.split(rf"{_BREAK}|\n[^\S\n]*\n", el.get_text(""))
    return "\n\n".join(p for p in (" ".join(part.split()) for part in parts) if p)


def _events(html: str) -> Iterator[tuple[str, str, str]]:
    """Yield (title, page_url, image_url) per card on the event calendar."""
    soup = BeautifulSoup(html, "html.parser")
    for card in soup.select("article"):
        link = card.select_one("a.exad-post-grid-title[href]")
        img = card.select_one("img.wp-post-image")
        if link:
            yield " ".join(link.get_text().split()), _absolute(link["href"]), _poster(img) if img else ""


def _event_page(html: str, day: date) -> tuple[time | None, str] | None:
    """(start, synopsis) from a broadcast's event page held on *day*; None when not a broadcast."""
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one(".page-content") or soup
    if not _BROADCAST.search(content.get_text(" ")):
        return None
    start = None
    synopsis: list[str] = []
    for p in content.find_all("p"):
        text = " ".join(p.get_text(" ").split())
        m = _EVENT_WHEN.search(text)
        if m and start is None and _MONTHS.get(m.group(2).lower()) == day.month and int(m.group(1)) == day.day:
            start = time(int(m.group(3)), int(m.group(4)))
        elif text.startswith("Köp biljetter"):
            break
        elif text and not m and (text := _BROADCAST_DATE.sub("", text).strip()):
            synopsis.append(text)
    return start, "\n\n".join(synopsis)
