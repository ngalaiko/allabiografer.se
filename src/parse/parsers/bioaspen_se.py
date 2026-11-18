"""Bio Aspen's own film programme and per-screening booking links."""

import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from parse import _http, _version
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

_SOURCE = "bioaspen_se"
_BASE = "https://www.bioaspen.se"
_PROGRAMME = _BASE + "/visningar/filmer/"
_VENUE = Venue(name="Aspen", city="Stockholm", address="Hägerstensvägen 100A")
_TZ = ZoneInfo("Europe/Stockholm")
_SESSION = re.compile(r"/shows/bio-aspen-.+-(?P<hall>\d+)-(?P<utc>\d{4}-\d{2}-\d{2}t\d{6})-0000000/")
_RUNTIME = re.compile(r"(?:(\d+) tim(?: (\d+) min)?|(\d+) min)")
REPLACES_VENUES = (("bioguiden_se", "Stockholm", "Aspen"), ("bio_se", "Stockholm", "Stockholm Bio Aspen"))


def parse() -> Iterator[Screening | Venue | Film]:
    session = _http.session()

    def page(url: str) -> BeautifulSoup:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")

    yield _VENUE
    url = _PROGRAMME
    visited: set[str] = set()
    movies: dict[str, None] = {}
    while url:
        if url in visited:
            raise ValueError(f"Aspen: programme pagination loop at {url}")
        visited.add(url)
        programme = page(url)
        cards = programme.select('.movie > a[href*="/movies/"]')
        if not cards:
            raise ValueError(f"Aspen: no film cards at {url}")
        movies.update(dict.fromkeys(urljoin(url, a["href"]) for a in cards))
        following = programme.select_one("a.next.page-numbers[href]")
        url = urljoin(url, following["href"]) if following else ""

    today = datetime.now(_TZ).date()
    seen: set[str] = set()
    for url in movies:
        movie = page(url)
        heading = movie.select_one("h1.entry-title")
        if not heading:
            raise ValueError(f"Aspen: missing film title at {url}")
        title = heading.get_text(" ", strip=True)
        description = movie.select_one(".entry-content p")
        director = movie.find("h3", string=re.compile(r"^\s*Regissör\s*$"))
        credits = director.find_next_sibling("span") if director else None
        rows = []
        runtimes: set[int] = set()
        for link in movie.select('a[href*="/shows/"]:has(h2)'):
            ticket = urljoin(url, link["href"])
            if ticket in seen:
                continue
            target = urlsplit(ticket)
            match = _SESSION.fullmatch(target.path) if target.netloc == urlsplit(_BASE).netloc else None
            if not match:
                raise ValueError(f"Aspen: unrecognised booking link {ticket}")
            start = datetime.strptime(match["utc"] + "+0000", "%Y-%m-%dt%H%M%S%z").astimezone(_TZ)
            if link.h2.get_text(strip=True) != start.strftime("%H:%M"):
                raise ValueError(f"Aspen: displayed time does not match booking link {ticket}")
            if start.date() < today:
                continue
            labels = [s.get_text(" ", strip=True) for s in link.select("span.font-menu")]
            audio = next((s[4:] for s in labels if s.startswith("TAL ")), "")
            subtitles = next((s[5:] for s in labels if s.startswith("TEXT ")), "")
            hall = next((s for s in labels if s == "Lusoperan" or s.startswith("Salong ")), "")
            if not hall:
                raise ValueError(f"Aspen: missing auditorium at {ticket}")
            if duration := next((m for s in labels if (m := _RUNTIME.fullmatch(s))), None):
                hours, minutes, only_minutes = duration.groups()
                runtimes.add(int(hours or 0) * 60 + int(minutes or only_minutes or 0))
            show_title = link.h3.get_text(" ", strip=True) if link.h3 else title
            # Keep event labels separate from the film identity.
            extra = (show_title,) if show_title != title else ()
            rows.append(
                Screening(
                    title=title,
                    tmdb_id=None,
                    date=start.date(),
                    time=start.time(),
                    ticket_url=ticket,
                    cinema_name=_VENUE.name,
                    city=_VENUE.city,
                    screen=hall,
                    **_version.screening_facts(language=audio, subtitles=subtitles, raw_attributes=extra),
                )
            )
            seen.add(ticket)
        if not rows:
            continue
        film = _films.make(
            _SOURCE,
            title,
            url=url,
            overview=description.get_text(" ", strip=True) if description else "",
            runtime=next(iter(runtimes)) if len(runtimes) == 1 else None,
            directors=[name.strip() for name in credits.get_text(" ", strip=True).split(",") if name.strip()]
            if credits
            else [],
        )
        yield film
        identifier = _tmdb(title, runtime=film.runtime)
        for row in rows:
            yield replace(row, tmdb_id=identifier, film_key=film.key)
