"""capitolbio.se — Bio & Bistro Capitol in Stockholm, dated public calendar."""

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, time

from bs4 import BeautifulSoup

from allabiografer import normalize as _version
from allabiografer.model import Film, Screening
from allabiografer.sources import _films

log = logging.getLogger(__name__)

_SOURCE = "capitolbio_se"
_SITE = "https://www.capitolbio.se"
_CINEMA = "Capitol"
_CITY = "Stockholm"
# Match allabiografer's rolling two-week programme, without Capitol's infinite scroll.
_DAYS = 14
_PREFIX = re.compile(r"^(afternoon tea|filmfeber|frukostbio|seniorbio|singalong|smygpremiär):\s*", re.IGNORECASE)
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
    year = film.release_date
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        for item in data.get("@graph", [data]):
            if item.get("@type") == "Movie" and re.fullmatch(r"\d{4}", str(item.get("copyrightYear", ""))):
                year = year or str(item["copyrightYear"])
    # The site's og:image is a landscape still, not a poster. Leave poster fallback to TMDB.
    return replace(
        film,
        release_date=year,
        runtime=int(runtime.group()) if runtime else None,
        overview=synopsis.get_text(" ", strip=True) if synopsis else "",
        directors=[name.strip() for name in fields.get("Regi", "").split(",") if name.strip()],
    )
