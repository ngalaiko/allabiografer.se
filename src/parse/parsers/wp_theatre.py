"""WordPress Theater plugin sites — wp_theatre_event blocks.

Discovers films from the homepage, then crawls each production page
for full screening data (dates, times, venues, ticket links).
"""

import logging
import re
from collections.abc import Iterator
from datetime import date, time

import requests
from bs4 import BeautifulSoup

from parse import _http, _version
from parse._util import infer_year
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue
from store.version import subtitles_label

log = logging.getLogger(__name__)

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

_SOURCE = "wp_theatre"
_SITES = [
    {
        "city": "Göteborg",
        "name": "Capitol",
        "url": "https://www.capitolgbg.se/",
        "address": "Skanstorget 1",
        # Ticket salongnr of each auditorium; other numbers book a series ("Cinemateket"), which the event venue names.
        "screens": {"1": "CAPITOL 1", "2": "CAPITOL 2"},
    },
]

# Post categories that label a programme series rather than a genre.
_NOT_GENRES = {"cinemateket", "unga-cinemateket"}
# Category slugs the theme strips diacritics from.
_GENRE_NAMES = {"dokumentar": "Dokumentär"}

# Programme series prefixed to the film title, e.g. "Cinemateket: Blade Runner".
_SERIES_PREFIX = re.compile(r"^(?:unga\s+)?cinemateket\s*(?::|[-–—])\s*", re.IGNORECASE)
# "1 tim 46 min" opening a paragraph.
_RUNTIME = re.compile(r"^(?:(\d+)\s*tim\w*)?\s*(?:(\d+)\s*min\b)?", re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
# "Japanskt och engelskt tal", "Dialog på norska", "Originalspråk: engelska", "Svensk text".
_SPOKEN = re.compile(
    r"\b(?:[^\W\d_]+t(?:\s*,\s*|\s+och\s+))*[^\W\d_]+t\s+tal\b|\bdialog\s+på\b|\b(?:original)?språk\s*:",
    re.IGNORECASE,
)
_SUBTITLED = re.compile(r"^[^\W\d_]+\s+text\b", re.IGNORECASE)
_DUBBED = re.compile(r"\bdubba[dt]\b", re.IGNORECASE)
# "tisdag 31 mars 16:00", "1 april, 2026 16:00".
_DATETIME = re.compile(
    r"(?P<day>\d{1,2})\s+(?P<month>[^\W\d_]+),?\s+(?:(?P<year>\d{4})\s+)?(?P<hour>\d{1,2}):(?P<minute>\d{2})"
)
# Ticket links name the date: "…&datum=2026-10-04".
_TICKET_DATE = re.compile(r"datum=(\d{4}-\d{2}-\d{2})")
# Ticket links name the auditorium: "…tomovie@salongnr=3&tid=18:30&datum=…".
_SALONG = re.compile(r"salongnr=(\d+)")
# Event remarks about ticket sales rather than the screening.
_SALES_NOTICE = re.compile(r"\s*(?:biljetter\s+ännu\s+ej\s+släppta|fler\s+visningar\s+tillkommer)\s*", re.IGNORECASE)


def _parse_datetime(text: str) -> tuple[date, time] | None:
    """Parse 'tisdag 31 mars 16:00', '1 april, 2026 16:00' or '12 september 2026 14:00'."""
    m = _DATETIME.search(text.strip())
    if not m:
        return None
    month = _MONTHS.get(m.group("month").lower())
    if not month:
        return None
    year = int(m.group("year")) if m.group("year") else infer_year(month)
    try:
        return date(year, month, int(m.group("day"))), time(int(m.group("hour")), int(m.group("minute")))
    except ValueError:
        return None


def _lookup_title(title: str) -> str:
    """Film title without the programme series it is listed under."""
    return _SERIES_PREFIX.sub("", title).strip()


def _parse_runtime(text: str) -> int | None:
    """Runtime in minutes from a paragraph opening with "1 tim 46 min"."""
    m = _RUNTIME.match(text)
    if not m or not (m.group(1) or m.group(2)):
        return None
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)


def _meta(soup: BeautifulSoup, prop: str) -> str:
    el = soup.select_one(f'meta[property="{prop}"][content]')
    return el.get("content", "").strip() if el else ""


def _genres(soup: BeautifulSoup) -> list[str]:
    """Genres from the production post's category classes."""
    post = soup.select_one("[id^=post-]")
    classes = post.get("class") or [] if post else []
    slugs = [c.removeprefix("category-") for c in classes if c.startswith("category-")]
    return [_GENRE_NAMES.get(s, s.replace("-", " ").capitalize()) for s in slugs if s not in _NOT_GENRES]


def _synopsis(soup: BeautifulSoup) -> tuple[str, int | None, str]:
    """Description, runtime and notes from the post body.

    The description ends at the runtime line; the notes are that line and what follows.
    """
    body = soup.select_one(".entry-content") or soup.select_one(".post-entry")
    if body is None:
        return "", None, ""

    paragraphs: list[str] = []
    notes: list[str] = []
    runtime = None
    for p in body.select("p"):
        # Showtime remarks live inside the listing, not the description.
        if p.find_parent(class_="wpt_listing"):
            continue
        text = p.get_text(" ", strip=True)
        if runtime is None:
            runtime = _parse_runtime(text)
        if runtime is not None:
            notes.append(text)
        elif text:
            paragraphs.append(text)
    return " ".join(paragraphs), runtime, " ".join(notes)


def _spoken(notes: str) -> tuple[str, str, bool]:
    """(language, subtitles, dubbed) the body notes state: "Italienskt tal, svensk text."."""
    language = subtitles = ""
    dubbed = False
    for sentence in _SENTENCE.split(_RUNTIME.sub("", notes.strip(), count=1).strip()):
        if m := _SPOKEN.search(sentence):
            text = sentence[m.end() :] if m.group(0).casefold().startswith("dialog") else sentence[m.start() :]
        elif _SUBTITLED.match(sentence):
            text = sentence
        else:
            continue
        spoken, subtitled = _version.from_text("Tal: " + text)
        if spoken and not language:
            language, dubbed = spoken, bool(_DUBBED.search(sentence))
        subtitles = subtitles or subtitled
    return language, subtitles, dubbed


def _remark(ev) -> tuple[str, str]:
    """(remark, subtitles) of one event: "ENGLISH SUBTITLES - ENGELSK TEXT", "HUNDBIO"."""
    el = ev.select_one(".wp_theatre_event_remark")
    remark = _SALES_NOTICE.sub(" ", el.get_text(" ", strip=True)).strip() if el else ""
    languages = _version.normalize(remark)[0].subtitles.languages if remark else None
    return remark, subtitles_label(sorted(lang.value for lang in languages)) if languages else ""


def _film(soup: BeautifulSoup, title: str) -> tuple[Film, int | None, str]:
    """Film metadata a production page carries, its runtime and body notes."""
    overview, runtime, notes = _synopsis(soup)
    language, _subtitles, dubbed = _spoken(notes)
    return (
        _films.make(
            _SOURCE,
            title,
            overview=overview,
            runtime=runtime,
            genres=_genres(soup),
            poster_url=_meta(soup, "og:image:secure_url") or _meta(soup, "og:image"),
            url=_meta(soup, "og:url"),
            original_languages=frozenset() if dubbed else _version.languages(language),
        ),
        runtime,
        notes,
    )


def _parse_production(html: str, site: dict) -> Iterator[Screening | Film]:
    """Yield the film listed on one production page, then every showtime."""
    psoup = BeautifulSoup(html, "html.parser")

    h1 = psoup.select_one("h1.wp_theatre_production_title") or psoup.select_one("h1")
    raw_title = _lookup_title(h1.get_text(strip=True) if h1 else "")
    film_title, fmt, language, subtitles = _version.split_title(raw_title)
    suffixes = _version.title_suffixes(raw_title)
    if not film_title:
        return

    film, runtime, notes = _film(psoup, film_title)
    spoken, subtitled, dubbed = _spoken(notes)
    dubbed = dubbed and not language
    language = language or spoken
    subtitles = subtitles or subtitled
    yield film
    tmdb_id = _tmdb(_lookup_title(film_title), runtime=runtime)

    # Sidebar widgets list other productions' events.
    listing = psoup.select_one(".wpt_context_production_events") or psoup
    for ev in listing.select(".wp_theatre_event"):
        dt_el = ev.select_one(".wp_theatre_event_datetime")
        venue_el = ev.select_one(".wp_theatre_event_venue")
        ticket_el = ev.select_one(".wp_theatre_event_tickets_url")

        if not dt_el:
            continue
        parsed = _parse_datetime(dt_el.get_text(strip=True))
        if not parsed:
            continue
        d, t = parsed

        ticket_url = ticket_el.get("href", "") if ticket_el else ""
        if not ticket_url:
            continue
        if dated := _TICKET_DATE.search(ticket_url):
            try:
                d = date.fromisoformat(dated.group(1))
            except ValueError:
                log.warning("bad ticket date %r for %r", dated.group(1), film_title)

        venue = venue_el.get_text(strip=True) if venue_el else ""
        salong = _SALONG.search(ticket_url)
        screen = site.get("screens", {}).get(salong.group(1), venue) if salong else venue
        remark, remark_subtitles = _remark(ev)
        attributes = (
            *suffixes,
            *((venue,) if venue and venue != screen else ()),
            *((remark,) if remark else ()),
        )

        yield Screening(
            tmdb_id=tmdb_id,
            title=film_title,
            date=d,
            time=t,
            ticket_url=ticket_url,
            cinema_name=site["name"],
            city=site["city"],
            screen=screen,
            **_version.screening_facts(
                format=fmt,
                language=language,
                subtitles=remark_subtitles or subtitles,
                audio_role_text="dubbad" if dubbed else "",
                source_texts=suffixes,
                raw_attributes=attributes,
            ),
            film_key=film.key,
        )


def parse() -> Iterator[Screening | Venue | Film]:
    session = _http.session()

    for site in _SITES:
        yield Venue(name=site["name"], city=site["city"], address=site.get("address", ""))
        log.info("wp_theatre: fetching %s", site["name"])
        yield from _parse_site(session, site)


def _parse_site(session: requests.Session, site: dict) -> Iterator[Screening | Film]:
    resp = session.get(site["url"], timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Discover production page URLs from event title links
    prod_urls: set[str] = set()
    for a in soup.select(".wp_theatre_event_title a[href]"):
        href = a.get("href", "")
        if href and "/produktion/" in href:
            prod_urls.add(href)

    log.info("  %d productions found", len(prod_urls))

    count = 0
    seen_films: set[str] = set()
    for url in sorted(prod_urls):
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.warning("failed to fetch production %s: %s", url, exc)
            continue

        for item in _parse_production(resp.text, site):
            if isinstance(item, Film):
                if item.key not in seen_films:
                    seen_films.add(item.key)
                    yield _films.register(item, session=session)
                continue
            yield item
            count += 1

    log.info("  %s: %d screenings", site["name"], count)
