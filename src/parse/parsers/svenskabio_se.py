"""Svenska Bio's own showtimes for Biostaden Eskilstuna."""

import re
from collections.abc import Iterator
from datetime import date, datetime
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from parse import _http, _version
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup
from store import Film, Screening, Venue

_SOURCE = "svenskabio_se"
_VENUE = Venue(name="Biostaden Eskilstuna", city="Eskilstuna", address="Kungsgatan 66")
REPLACES_VENUES = (("filmstaden_se", _VENUE.city, _VENUE.name),)
_FEED = "https://svenskabio.se/wp-json/evermade/v1/movie-feed"
_PARAMS = {
    "cityId": 4,
    "cinemaIds": 3,
    "cinemaId": 0,
    "movieType": "current",
    "includeCampaign": 1,
    "view": "showtimes",
    "dateHorizon": 0,
    "moviePostId": 0,
    "genreIds": "",
    "showtimeCard": "movie",
}
_CARD = ".em-block-showtime-movie-card"


def parse() -> Iterator[Screening | Venue | Film]:
    session = _http.session()

    def fetch(day: str) -> dict:
        response = session.get(_FEED, params={**_PARAMS, "date": day}, timeout=20)
        response.raise_for_status()
        return response.json()

    first = fetch("all")
    days = sorted({date.fromisoformat(p["value"]).isoformat() for p in first["dateOptions"] if p["value"] != "all"})
    films: dict[str, Film] = {}
    seen: set[str] = set()
    yield _VENUE
    for day in days:
        payload = first if first["date"] == day else fetch(day)
        cards = BeautifulSoup(payload["html"], "html.parser").select(_CARD)
        if payload["date"] != day or not cards:
            raise ValueError(f"svenskabio: missing advertised programme for {day}")
        for card in cards:
            when = datetime.fromisoformat(card.select_one(f"{_CARD}__time")["datetime"])
            wrapper = card.select_one(f"{_CARD}__card-link")["href"]
            (ticket,) = parse_qs(urlsplit(wrapper).query)["url"]
            show_id = card["data-showtime-id"].removesuffix("_sv")
            if (
                when.date().isoformat() != day
                or not show_id.isdecimal()
                or ticket != f"https://biljetter.svenskabio.se/seat-plan/{show_id}"
            ):
                raise ValueError(f"svenskabio: inconsistent showtime {show_id} on {day}")
            if show_id in seen:
                continue
            seen.add(show_id)
            title = card.select_one(f"{_CARD}__title").get_text(" ", strip=True)
            meta = [n.get_text(strip=True) for n in card.select(f"{_CARD}__meta-item")]
            length = next((m for value in meta if (m := re.fullmatch(r"(\d+):([0-5]\d)", value))), None)
            runtime = int(length[1]) * 60 + int(length[2]) if length else None
            film = _films.make(_SOURCE, title, runtime=runtime, url=card.select_one(f"{_CARD}__title a")["href"])
            films.setdefault(film.key, film)
            labels = {
                label.get_text(strip=True): label.parent.select_one(f"{_CARD}__label-text").get_text(strip=True)
                for label in card.select(f"{_CARD}__label .screen-reader-text")
            }
            sold_out = any(n.get_text(strip=True) == "Slutsålt" for n in card.select(f"{_CARD}__availability span"))
            yield Screening(
                tmdb_id=lookup(title, runtime=runtime),
                title=title,
                film_key=film.key,
                city=_VENUE.city,
                cinema_name=_VENUE.name,
                date=when.date(),
                time=when.time(),
                screen=card.select_one(f"{_CARD}__screen").get_text(" ", strip=True),
                ticket_url=ticket,
                **_version.screening_facts(
                    language=labels.get("Tal:", ""),
                    subtitles=labels.get("Text:", ""),
                    raw_attributes=("Slutsålt",) if sold_out else (),
                ),
            )
    yield from films.values()
