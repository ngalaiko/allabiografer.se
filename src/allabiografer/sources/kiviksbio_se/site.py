"""kiviksbio.se — WordPress Events Manager plugin."""

import logging
import re
from collections.abc import Iterator
from datetime import date, time

from bs4 import BeautifulSoup, Tag

from allabiografer import normalize as _version
from allabiografer.dates import infer_year
from allabiografer.model import Film
from allabiografer.sources import _films

log = logging.getLogger(__name__)

_SOURCE = "kiviksbio_se"
_URL = "https://www.kiviksbio.se/evenemang/"
_CINEMA = "Kiviks Bio"
_CITY = "Kivik"
_ADDRESS = "Ordensgatan 5"

# The listing's only non-genre category.
_NOT_A_GENRE = {"film"}

# Live broadcast prefixes: opera, ballet, concerts.
_BROADCAST = re.compile(r"direkt\s+från\s+[^:]+|met\s+live|live\s+på\s+bio", re.IGNORECASE)
# Title prefixes: "Extra-visning (2) ", "Höstlovsfilm! ", "PREMIÄR! ", "Direkt från Metropolitanoperan: ".
_TITLE_PREFIX = re.compile(
    r"^(?:(?P<extra>extra-?visning)(?:\s*\(\d+\))?|(?P<word>[^\W\d_][\w-]*)!"
    rf"|(?P<broadcast>{_BROADCAST.pattern})\s*:)\s+",
    re.IGNORECASE,
)
# End time the listing gives events without a known length.
_NO_END = "23:59"
# Block elements whose text forms a paragraph.
_BLOCKS = ["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"]
# "Otello ." — a space the editor left before punctuation.
_LOOSE_PUNCTUATION = re.compile(r" +([.,;:!?])(?=\s|$)")
# Marks block boundaries; source newlines are formatting whitespace.
_BREAK = "\u2029"
# Credits, prices and side events that follow the synopsis.
_TRAILER = re.compile(
    r"\b(?:Regi|Dirigent|Land|Pris)\s*:|\bTextas\s+på\b|\bFöreställningen har\b|\bOBS!",
    re.IGNORECASE,
)
# "Textas på svenska!", "Svensk text".
_SUBTITLES = re.compile(r"\btextas\s+på\s+([^\W\d_]+)|\b([^\W\d_]+)\s+text\b", re.IGNORECASE)

_MONTHS = (
    "januari",
    "februari",
    "mars",
    "april",
    "maj",
    "juni",
    "juli",
    "augusti",
    "september",
    "oktober",
    "november",
    "december",
)


def _month(name: str) -> int | None:
    """Month number from a Swedish month name or an abbreviation of at least three letters."""
    name = name.lower()
    return next((i for i, full in enumerate(_MONTHS, 1) if len(name) >= 3 and full.startswith(name)), None)


def _runtime(start: time, end_text: str) -> int | None:
    """Minutes between the listed start and end times."""
    m = re.match(r"(\d{1,2}):(\d{2})", end_text)
    if not m or m.group(0) == _NO_END:
        return None
    minutes = (int(m.group(1)) * 60 + int(m.group(2))) - (start.hour * 60 + start.minute)
    if minutes <= 0:
        minutes += 24 * 60
    return minutes


def _split_title(title: str) -> tuple[str, tuple[str, ...]]:
    """Title without its programme prefixes, and the prefixes."""
    labels: list[str] = []
    while m := _TITLE_PREFIX.match(title):
        labels.append(" ".join((m.group("extra") or m.group("word") or m.group("broadcast")).split()))
        title = title[m.end() :]
    return title, tuple(labels)


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


def _content(page: str) -> str:
    """Event page body text, one paragraph per block element, separated by blank lines."""
    content = BeautifulSoup(page, "html.parser").select_one(".em-event-content")
    if not content:
        return ""
    for br in content.find_all("br"):
        br.replace_with(" ")
    for block in content.find_all(_BLOCKS):
        block.insert_before(_BREAK)
        block.insert_after(_BREAK)
    paragraphs = (" ".join(part.split()) for part in content.get_text("").split(_BREAK))
    return _LOOSE_PUNCTUATION.sub(r"\1", "\n\n".join(p for p in paragraphs if p))


def _overview(page: str) -> str:
    """Synopsis from an event page, up to the credits."""
    text = _content(page)
    m = _TRAILER.search(text)
    return text[: m.start()].strip() if m else text


def _directors(page: str) -> list[str]:
    """Labelled directors, excluding filmography, country and conductor credits."""
    match = re.search(r"^Regi\s*:\s*([^\n]+)", _content(page), re.IGNORECASE | re.MULTILINE)
    if not match:
        return []
    credit = re.split(r"\(|" + _TRAILER.pattern, match.group(1), maxsplit=1, flags=re.IGNORECASE)[0]
    return [name.strip() for name in re.split(r",|\s+och\s+|\s*&\s*", credit) if name.strip()]


def _subtitles(page: str) -> dict[str, object]:
    """Screening version fields from an event page's subtitle note."""
    for m in _SUBTITLES.finditer(_content(page)):
        label = _version.subtitles(m.group(1) or m.group(2))
        facts = _version.screening_facts(subtitles=label)
        if facts["version"].subtitles.languages:
            return facts
    return _version.screening_facts()


def _showtimes(page: str, *, year_for_month=infer_year) -> Iterator[tuple[Film, date, time, str, tuple[str, ...]]]:
    """Yield (film, date, time, ticket_url, title prefixes) per event item."""
    soup = BeautifulSoup(page, "html.parser")

    for ev in soup.select(".em-item"):
        title_el = ev.select_one(".em-item-title a")
        date_el = ev.select_one(".em-event-date")
        if not title_el or not date_el:
            continue

        # Titles carry indentation runs that HTML rendering collapses.
        film_title, labels = _split_title(" ".join(title_el.get_text().split()))
        ticket_url = title_el.get("href", "")

        # Parse "onsdag 1 apr kl 15:00 - 16:45"
        date_text = date_el.get_text(strip=True)
        m = re.match(r"\w+\s+(\d{1,2})\s+(\w+)\s+kl\s+(\d{1,2}):(\d{2})(?:\s*-\s*(\d{1,2}:\d{2}))?", date_text)
        if not film_title or not ticket_url:
            continue
        month = _month(m.group(2)) if m else None
        if not month:
            log.warning("kiviksbio.se: unparseable date %r for %s", date_text, film_title)
            continue

        day = int(m.group(1))

        d = date(year_for_month(month), month, day)
        t = time(int(m.group(3)), int(m.group(4)))

        yield _film(ev, film_title, ticket_url, _runtime(t, m.group(5) or "")), d, t, ticket_url, labels
