"""The cinema's own dated programme, including its session-specific ticket links."""

import re
from collections.abc import Iterator
from datetime import datetime
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from parse import _http, _version
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

_BASE = "https://biofagelbla.se"
_VENUE = Venue(name="Stockholm Bio Fågel Blå", city="Stockholm", address="Skeppargatan 60")
_TZ = ZoneInfo("Europe/Stockholm")
_RUNTIME = re.compile(r"(?:(\d+)h(?: (\d+) mins?)?|(\d+) mins?)")
REPLACES_VENUES = (("bio_se", _VENUE.city, _VENUE.name),)


def parse() -> Iterator[Screening | Venue | Film]:
    session = _http.session()
    response = session.get(f"{_BASE}/program/", timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    cards = soup.select(".js-movie-listing-by-date article")
    if not cards:
        raise ValueError("Fågel Blå: no programme cards")
    yield _VENUE

    today = datetime.now(_TZ).date()
    seen: set[str] = set()
    films: dict[str, Film] = {}
    identifiers: dict[str, int | None] = {}
    for card in cards:
        clock = card.select_one("h3 time[datetime]")
        if clock is None:
            raise ValueError("Fågel Blå: missing programme time")
        start = datetime.fromisoformat(clock["datetime"])
        if start.tzinfo is None or start.astimezone(_TZ).strftime("%H:%M") != clock.get_text(strip=True):
            raise ValueError(f"Fågel Blå: inconsistent programme time {start}")
        start = start.astimezone(_TZ)
        heading = clock.parent
        clock.extract()
        title = heading.get_text(" ", strip=True)
        if start.date() < today or "slutet sällskap" in title.casefold():
            continue

        link = card.select_one('a[href*="showtime="]')
        if link is None:
            raise ValueError(f"Fågel Blå: missing ticket link for {title} at {start}")
        ticket = link["href"]
        target = urlsplit(ticket)
        show_ids = parse_qs(target.query).get("showtime", [])
        if target.netloc != "biofagelbla.se" or len(show_ids) != 1 or not show_ids[0].isdigit():
            raise ValueError(f"Fågel Blå: invalid ticket link {ticket}")
        if show_ids[0] in seen:
            continue
        seen.add(show_ids[0])

        labels = [tag.get_text(" ", strip=True) for tag in card.select("span.leading-none")]
        audio = next((text.removeprefix("Språk: ") for text in labels if text.startswith("Språk: ")), "")
        subtitles = next((text.removeprefix("Text: ") for text in labels if text.startswith("Text: ")), "")
        film_url = _BASE + target.path
        if film_url not in films:
            runtime = None
            if duration := next((m for text in labels if (m := _RUNTIME.fullmatch(text))), None):
                hours, minutes, only_minutes = duration.groups()
                runtime = int(hours or 0) * 60 + int(minutes or only_minutes or 0)
            response = session.get(film_url, timeout=30)
            response.raise_for_status()
            details = BeautifulSoup(response.text, "html.parser")
            description = details.select_one('meta[name="description"]')
            films[film_url] = film = _films.make(
                "biofagelbla_se",
                title,
                url=film_url,
                runtime=runtime,
                overview=description.get("content", "") if description else "",
            )
            identifiers[film_url] = _tmdb(film.title, runtime=film.runtime)
            yield film
        yield Screening(
            title=films[film_url].title,
            tmdb_id=identifiers[film_url],
            date=start.date(),
            time=start.time(),
            ticket_url=ticket,
            cinema_name=_VENUE.name,
            city=_VENUE.city,
            film_key=films[film_url].key,
            **_version.screening_facts(language=audio, subtitles=_version.subtitles(subtitles)),
        )
