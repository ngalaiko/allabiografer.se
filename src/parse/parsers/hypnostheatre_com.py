"""hypnostheatre.com — Hypnos Theatre, Malmö; bespoke WordPress theme listing every event on the homepage."""

import logging
import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, time
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from parse import _http, _version
from parse._util import infer_year
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

log = logging.getLogger(__name__)

_SOURCE = "hypnostheatre_com"
_URL = "https://hypnostheatre.com/"
_CINEMA = "Hypnos Theatre"
_CITY = "Malmö"
_ADDRESS = "Norra Grängesbergsgatan 15"

# Filter labels of film events; "LIVE EVENT" alone is not a screening.
_FILM_CATEGORIES = {"FILMKLUBB", "MOVIES"}
# "Sat Oct 3".
_DATE = re.compile(r"(\w{3})\s+(\d{1,2})$")
# "Chad Stahelski, 2014 · 101' · English"; language optional.
_CREDITS = re.compile(r"^.+,\s*(\d{4})\s*·\s*(\d+)['\u2019](?:\s*·\s*(.+))?$")
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

        year = runtime = None
        language = ""
        labels: list[str] = []
        for meta in row.select(".screening-meta"):
            text = _text(meta)
            if credits := _CREDITS.match(text):
                year, runtime, language = credits[1], int(credits[2]), credits[3] or ""
            elif text:
                labels.append(text)

        film = _films.make(
            _SOURCE,
            title,
            runtime=runtime,
            release_date=year or "",
            overview=_overview(row),
            url=_URL,
        )
        yield (
            film,
            Screening(
                tmdb_id=None,
                title=film.title,
                film_key=film.key,
                date=date(infer_year(month), month, int(m[2])),
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


def _tmdb_id(film: Film) -> int | None:
    """TMDB match by title, year and runtime, else by title and year."""
    year = int(film.release_date) if film.release_date else None
    return (film.runtime and _tmdb(film.title, runtime=film.runtime, year=year)) or _tmdb(film.title, year=year)


def parse() -> Iterator[Screening | Venue | Film]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)
    session = _http.session()
    resp = session.get(_URL, timeout=15)
    resp.raise_for_status()

    ids: dict[str, int | None] = {}
    for film, screening in _showtimes(resp.text):
        if film.key not in ids:
            ids[film.key] = _tmdb_id(film)
            yield _films.register(film, session=session)
        yield replace(screening, tmdb_id=ids[film.key])
