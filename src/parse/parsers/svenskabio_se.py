"""Showtimes for cinemas that have moved to Svenska Bio's own website."""

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
_CINEMAS = (
    (4, 3, Venue(name="Biostaden Eskilstuna", city="Eskilstuna", address="Kungsgatan 66")),
    (5, 4, Venue(name="Biostaden Uddevalla", city="Uddevalla", address="Göteborgsvägen 11A")),
)
REPLACES_VENUES = (
    *tuple(("filmstaden_se", venue.city, venue.name) for _, _, venue in _CINEMAS),
    ("bioguiden_se", "Uddevalla", "Biostaden Uddevalla"),
)
_FEED = "https://svenskabio.se/wp-json/evermade/v1/movie-feed"
_PARAMS = {
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
    films: dict[str, Film] = {}
    for city_id, cinema_id, venue in _CINEMAS:
        yield from _programme(session, city_id, cinema_id, venue, films)
    yield from films.values()


def _programme(
    session, city_id: int, cinema_id: int, venue: Venue, films: dict[str, Film]
) -> Iterator[Screening | Venue]:
    def fetch(day: str) -> dict:
        response = session.get(
            _FEED, params={**_PARAMS, "cityId": city_id, "cinemaIds": cinema_id, "date": day}, timeout=20
        )
        response.raise_for_status()
        return response.json()

    first = fetch("all")
    days = sorted({date.fromisoformat(p["value"]).isoformat() for p in first["dateOptions"] if p["value"] != "all"})
    if not days:
        raise ValueError(f"svenskabio: missing advertised dates for {venue.name}")
    seen: set[str] = set()
    yield venue
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
            yield Screening(
                tmdb_id=lookup(title, runtime=runtime),
                title=title,
                film_key=film.key,
                city=venue.city,
                cinema_name=venue.name,
                date=when.date(),
                time=when.time(),
                screen=card.select_one(f"{_CARD}__screen").get_text(" ", strip=True),
                ticket_url=ticket,
                **_version.screening_facts(
                    language=labels.get("Tal:", ""),
                    subtitles=labels.get("Text:", ""),
                ),
            )
