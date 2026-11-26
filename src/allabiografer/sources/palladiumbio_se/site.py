"""palladiumbio.se — Filmhuset Palladium, Arvika."""

import logging
import re
from datetime import date, time
from typing import TYPE_CHECKING, NamedTuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from allabiografer import normalize as _version
from allabiografer.dates import infer_year
from allabiografer.sources import _films

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from allabiografer.model import Film

log = logging.getLogger(__name__)

_SOURCE = "palladiumbio_se"
_URL = "https://palladiumbio.se/"
_CINEMA = "Filmhuset Palladium"
_CITY = "Arvika"
_ADDRESS = "Hamngatan 11"

# Programme labels prefixed to titles: "SMYGPREMIÄR! Bortglömda ön", "SMYGPREMIÄRHeart of the Beast".
_PREFIX = re.compile(
    r"^(?P<tag>smygpremiär|förhandsvisning|premiär|bio\s?passet|bio\s?kontrast|knattebio|barnvagnsbio|klassiker)"
    r"(?P<sep>\s*[!:]|\s*[-–]\s)?\s*(?=\S)",
    re.IGNORECASE,
)
# "(Tal: Svenska (dubbat))" — one level of nesting.
_TAG = re.compile(r"\((?:[^()]|\([^()]*\))*\)")
# Hero background on event pages: landscape.
_HERO = re.compile(r"url\(['\"]?([^'\")]+/eventImages/[^'\")]+)")

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


def _split_prefix(raw: str) -> tuple[str, str]:
    """(programme label, rest).

    A label without punctuation counts only in capitals, followed by a space or a
    capitalised word: "SMYGPREMIÄRHeart of the Beast", not "PREMIÄRDANSEN".
    """
    raw = raw.strip()
    m = _PREFIX.match(raw)
    if not m:
        return "", raw
    rest = raw[m.end() :]
    if not m.group("sep"):
        glued = m.group(0) == m.group("tag")
        if not m.group("tag").isupper() or (glued and not (rest[:1].isupper() and rest[1:2].islower())):
            return "", raw
    return raw[: m.end()].strip(), rest


def _attributes(raw: str) -> tuple[str, ...]:
    """Raw programme label and version tags around the title."""
    prefix, rest = _split_prefix(raw)
    return ((prefix,) if prefix else ()) + tuple(_TAG.findall(rest))


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

    # Strip the programme label and everything from first parenthesis for the title
    title = re.sub(r"\s*\(.*", "", _split_prefix(raw)[1]).strip()

    return title, _version.language(language), _version.subtitles(subtitles)


def _parse_screen(venue_text: str) -> str:
    """Extract screen name from venue text like 'Filmhuset Palladium Arvika, Salong 2'."""
    m = re.search(r",\s*(Salong\s+\S+)", venue_text)
    return m.group(1) if m else ""


def _overview(page: str) -> str:
    """Synopsis from a film page; the paragraphs precede the showings table."""
    soup = BeautifulSoup(page, "html.parser")
    return " ".join(" ".join(p.get_text(" ") for p in soup.select("main .lead > p")).split())


def _norm(title: str) -> str:
    return "".join(c for c in title.casefold() if c.isalnum())


class _Posters(NamedTuple):
    """Carousel posters keyed by normalised card title, and by the part before a card's colon."""

    cards: dict[str, str]
    prefixes: dict[str, str]


def _posters(html: str) -> _Posters:
    """Portrait posters from the "Aktuellt" carousel.

    Cards carry no link; "DIGGER:BIO PASSET" also keys by the part before the colon.
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for card in soup.select(".multiCarousel .card"):
        title_el = card.select_one(".card-title")
        img = card.select_one("img[src]")
        if title_el and img:
            cards.append((title_el.get_text(strip=True), urljoin(_URL, img.get("src", ""))))
    full = {_norm(title): src for title, src in cards}
    prefixes: dict[str, str] = {}
    for title, src in cards:
        prefixes.setdefault(_norm(title.split(":")[0]), src)
    full.pop("", None)
    prefixes.pop("", None)
    return _Posters(full, prefixes)


def _poster(posters: _Posters, title: str, programme: Iterable[str] = ()) -> str:
    """Poster of the card naming *title*.

    A card shortened to the part before the title's colon ("SMÅSTADSLIV") matches only
    when no other film in *programme* shares that part.
    """
    key = _norm(title)
    if src := posters.cards.get(key) or posters.prefixes.get(key):
        return src
    if ":" not in title:
        return ""
    prefix = _norm(title.split(":")[0])
    sharing = {_norm(t) for t in programme if _norm(t.split(":")[0]) == prefix}
    return posters.cards.get(prefix, "") if len(sharing) == 1 else ""


def _hero(page: str) -> str:
    """Landscape event image from a film page's hero background."""
    m = _HERO.search(page)
    return urljoin(_URL, m.group(1)) if m else ""


def _parse_date(text: str, *, year_for_month=infer_year) -> date | None:
    """Date from a header like "Onsdag 1 april"."""
    m = re.match(r"\w+\s+(\d{1,2})\s+(\w+)", text)
    month = _MONTHS.get(m.group(2).lower()) if m else None
    if not month:
        return None
    try:
        return date(year_for_month(month), month, int(m.group(1)))
    except ValueError:
        return None


def _showtimes(
    html: str, *, year_for_month=infer_year
) -> Iterator[tuple[Film, date, time, str, str, str, str, tuple[str, ...]]]:
    """Yield (film, date, time, ticket_url, screen, language, subtitles, raw_attributes) per program row."""
    soup = BeautifulSoup(html, "html.parser")

    current_date: date | None = None

    for tr in soup.select("table.tableBioprogram tr"):
        # Date header row
        th = tr.select_one("th.date")
        if th:
            text = th.get_text(strip=True)
            current_date = _parse_date(text, year_for_month=year_for_month)
            if current_date is None:
                log.warning("palladiumbio.se: skipping rows under date %r", text)
            continue

        if current_date is None:
            continue

        time_el = tr.select_one("td.time span")
        title_el = tr.select_one("td.title a")
        venue_el = tr.select_one("td.venue")
        buy_el = tr.select_one("td.buy a.btn-primary")

        if not time_el or not title_el:
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

        # Sold-out and not-yet-on-sale rows lack the buy button; their event page stands in.
        ticket_url = (buy_el and buy_el.get("href", "")) or urljoin(_URL, title_el.get("href", ""))

        screen = _parse_screen(venue_el.get_text(strip=True)) if venue_el else ""

        # Every showing is its own event; its page carries the film's synopsis.
        film = _films.make(_SOURCE, film_title, url=title_el.get("href", ""))

        yield film, current_date, t, ticket_url, screen, language, subtitles, _attributes(raw_title)
