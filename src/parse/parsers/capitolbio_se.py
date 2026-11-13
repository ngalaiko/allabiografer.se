"""capitolbio.se — Bio & Bistro Capitol in Stockholm, dated public calendar."""

import logging
import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from parse import _http, _version
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

log = logging.getLogger(__name__)

_SOURCE = "capitolbio_se"
_SITE = "https://www.capitolbio.se"
_CINEMA = "Capitol"
_CITY = "Stockholm"
_TZ = ZoneInfo("Europe/Stockholm")
# Match allabiografer's rolling two-week programme, without Capitol's infinite scroll.
_DAYS = 14
_PREFIX = re.compile(r"^(afternoon tea|frukostbio|seniorbio|singalong|smygpremiär):\s*", re.IGNORECASE)
_PREMIERE = re.compile(r"\s+[-–]\s+Premiär\b.*$", re.IGNORECASE)
# The cinema also sells a wine tasting through its film calendar.
_NOT_FILMS = {"Vinkväll med Alf & Petter"}


def _page(html: str) -> BeautifulSoup:
    """Apply Next.js's streamed Suspense replacements before reading the HTML."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.select("script"):
        for target, source in re.findall(r'\$RC\("([^"]+)","([^"]+)"\)', script.string or ""):
            placeholder, content = soup.find(id=target), soup.find(id=source)
            if placeholder is not None and content is not None:
                placeholder.replace_with(*list(content.contents))
                content.decompose()
    return soup


def _showtimes(html: str, day: date) -> Iterator[tuple[Film, Screening]]:
    soup = _page(html)
    # A truncated day must fail rather than replace stored data with a partial programme.
    if any("Ladda fler visningar" in button.get_text() for button in soup.select("button")):
        raise ValueError(f"Capitol: incomplete calendar for {day}")

    seen: set[str] = set()
    for link in soup.select('a[href^="/boka/"]'):
        ticket = _SITE + link["href"]
        if ticket in seen:
            continue
        seen.add(ticket)
        # Each calendar card contains a title/booking link, facts, and a film link.
        card = link.find_parent("div")
        detail = card.select_one('a[href^="/filmer/"]') if card else None
        if detail is None:
            continue
        clock = link.select_one("span.sr-only")
        screen = link.select_one('[aria-hidden="true"]')
        facts = card.select_one("span.truncate")
        raw_title = " ".join(str(t).strip() for t in link.find_all(string=True, recursive=False)).strip()
        if raw_title in _NOT_FILMS:
            continue
        prefix = _PREFIX.match(raw_title)
        title = _PREMIERE.sub("", raw_title[prefix.end() :] if prefix else raw_title)
        title = re.sub(r"\s+med besök$", "", title, flags=re.IGNORECASE)
        title, fmt, language, subtitles = _version.split_title(title)
        year = re.search(r"\s+\((\d{4})\)$", title)
        if year:
            title = title[: year.start()]
        spoken, _, subtitled = (facts.get_text(" ", strip=True) if facts else "").partition("|")
        labels = link.find_next_sibling("div")
        attributes = tuple(filter(None, (raw_title if raw_title != title else "", labels.get_text(" ", strip=True))))
        film = _films.make(_SOURCE, title, url=_SITE + detail["href"], release_date=year[1] if year else "")
        yield (
            film,
            Screening(
                title=title,
                film_key=film.key,
                tmdb_id=None,
                date=day,
                time=time.fromisoformat(clock.get_text(strip=True).strip(" ()")),
                cinema_name=_CINEMA,
                city=_CITY,
                screen=screen.get_text("", strip=True).replace("Salong", "Salong ", 1) if screen else "",
                ticket_url=ticket,
                **_version.screening_facts(
                    format=fmt,
                    language=spoken or language,
                    subtitles=subtitled or subtitles,
                    source_texts=(raw_title,),
                    raw_attributes=attributes,
                ),
            ),
        )


def _details(html: str, film: Film) -> Film:
    soup = _page(html)
    fields = {
        dt.get_text(strip=True): dt.find_next_sibling("dd").get_text(" ", strip=True)
        for dt in soup.select("dl dt")
        if dt.find_next_sibling("dd") is not None
    }
    runtime = re.search(r"\d+", fields.get("Längd", ""))
    synopsis = soup.select_one(".mcc-content")
    # The site's og:image is a landscape still, not a poster. Leave poster fallback to TMDB.
    return replace(
        film,
        runtime=int(runtime.group()) if runtime else None,
        overview=synopsis.get_text(" ", strip=True) if synopsis else "",
    )


def parse() -> Iterator[Screening | Venue | Film]:
    yield Venue(name=_CINEMA, city=_CITY, address="Sankt Eriksgatan 82")
    session = _http.session()
    today = datetime.now(_TZ).date()
    films: dict[str, Film] = {}
    count = 0
    for offset in range(_DAYS):
        day = today + timedelta(days=offset)
        response = session.get(f"{_SITE}/filmer?datum={day.isoformat()}", timeout=30)
        response.raise_for_status()
        for film, screening in _showtimes(response.text, day):
            if film.url not in films:
                try:
                    detail = session.get(film.url, timeout=30)
                    detail.raise_for_status()
                    film = _details(detail.text, film)
                except requests.RequestException as exc:
                    log.warning("Capitol: film details failed for %s: %s", film.url, exc)
                films[film.url] = film
                yield _films.register(film, session=session)
            film = films[film.url]
            yield replace(
                screening,
                tmdb_id=_tmdb(
                    film.title, runtime=film.runtime, year=int(film.release_date) if film.release_date else None
                ),
            )
            count += 1
    log.info("capitolbio.se: %d screenings", count)
