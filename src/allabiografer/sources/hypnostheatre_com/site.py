"""hypnostheatre.com — Hypnos Theatre, Malmö; bespoke WordPress theme listing every event on the homepage."""

import logging
import re
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from allabiografer import normalize as _version
from allabiografer.dates import infer_year
from allabiografer.model import Film, Screening
from allabiografer.sources import _films

if TYPE_CHECKING:
    from collections.abc import Iterator

log = logging.getLogger(__name__)

_SOURCE = "hypnostheatre_com"
_URL = "https://hypnostheatre.com/"
_CINEMA = "Hypnos Theatre"
_CITY = "Malmö"
_ADDRESS = "Norra Grängesbergsgatan 15"
_TZ = ZoneInfo("Europe/Stockholm")

# Filter labels of film events; "LIVE EVENT" alone is not a screening.
_FILM_CATEGORIES = {"FILMKLUBB", "MOVIES"}
# "Sat Oct 3".
_DATE = re.compile(r"(\w{3})\s+(\d{1,2})$")
# "Chad Stahelski, 2014 · 101' · English"; language optional.
_CREDITS = re.compile(r"^(.+),\s*(\d{4})\s*·\s*(\d+)['\u2019](?:\s*·\s*(.+))?$")
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def _text(el: Tag | None) -> str:
    return " ".join(el.get_text().split()) if el else ""


def _ticket_url(row: Tag) -> str:
    """Ticket tag link without its query, else the listing."""
    a = row.select_one("a.tag[href]")
    if not a:
        return _URL
    parts = urlsplit(a["href"])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _overview(row: Tag) -> str:
    desc = row.select_one(".screening-description")
    if not desc:
        return ""
    blocks = desc.find_all(["p", "div"], recursive=False) or [desc]
    return "\n\n".join(text for b in blocks if (text := _text(b)))


def _categories(soup: BeautifulSoup) -> dict[str, str]:
    """Row class → filter label, e.g. "cat-2" → "FILMKLUBB"."""
    return {b["data-filter"]: _text(b) for b in soup.select(".filter-pill[data-filter]")}


def _screening_date(row: Tag, month: int, day: int, start: time) -> date | None:
    """Use the calendar's explicit year only when its local date and time agree with the listing."""
    calendar = row.select_one('a[href*="google.com/calendar"]')
    if calendar is None:
        return date(infer_year(month), month, day)
    stamp = parse_qs(urlsplit(calendar["href"]).query).get("dates", [""])[0].split("/")[0]
    try:
        stated = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).astimezone(_TZ)
    except ValueError:
        log.warning("hypnostheatre.com: invalid calendar date %r", stamp)
        return None
    if (stated.month, stated.day, stated.time()) != (month, day, start):
        log.warning("hypnostheatre.com: calendar %s conflicts with listing %02d/%02d %s", stamp, day, month, start)
        return None
    return stated.date()


def _showtimes(html: str) -> Iterator[tuple[Film, Screening]]:
    soup = BeautifulSoup(html, "html.parser")
    categories = _categories(soup)
    for row in soup.select(".screening-row"):
        if not any(categories.get(c) in _FILM_CATEGORIES for c in row.get("class", [])):
            continue
        title = _text(row.select_one(".screening-film-title"))
        date_text = _text(row.select_one(".screening-date"))
        time_text = _text(row.select_one(".screening-time"))
        if not title or not time_text:
            continue
        m = _DATE.search(date_text)
        if not m or m[1].lower() not in _MONTHS:
            log.warning("hypnostheatre.com: unparseable date %r for %s", date_text, title)
            continue
        try:
            t = time.fromisoformat(time_text)
        except ValueError:
            log.warning("hypnostheatre.com: unparseable time %r for %s", time_text, title)
            continue
        month = _MONTHS.index(m[1].lower()) + 1
        screening_date = _screening_date(row, month, int(m[2]), t)
        if screening_date is None:
            continue

        year = runtime = None
        language = ""
        directors: list[str] = []
        labels: list[str] = []
        for meta in row.select(".screening-meta"):
            text = _text(meta)
            if credits := _CREDITS.match(text):
                year, runtime, language = credits[2], int(credits[3]), credits[4] or ""
                directors = [name.strip() for name in re.split(r",|&| and ", credits[1]) if name.strip()]
            elif text:
                labels.append(text)

        film = _films.make(
            _SOURCE,
            title,
            runtime=runtime,
            release_date=year or "",
            overview=_overview(row),
            url=_URL,
            directors=directors,
            # "French, Mandarin · English subtitles": spoken languages precede the subtitles.
            original_languages=_version.languages(language.split("·")[0]),
        )
        yield (
            film,
            Screening(
                tmdb_id=None,
                title=film.title,
                film_key=film.key,
                date=screening_date,
                time=t,
                ticket_url=_ticket_url(row),
                cinema_name=_CINEMA,
                city=_CITY,
                **_version.screening_facts(
                    language=_version.language(language) if language else "",
                    raw_attributes=tuple(labels),
                ),
            ),
        )
