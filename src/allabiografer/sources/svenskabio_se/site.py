"""Showtimes for cinemas that have moved to Svenska Bio's own website."""

import re
from collections.abc import Iterator
from datetime import date, datetime
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from allabiografer import normalize as _version
from allabiografer.model import Film, Screening, Venue
from allabiografer.sources import _films

_SOURCE = "svenskabio_se"
_CINEMAS = (
    (4, 3, Venue(name="Biostaden Eskilstuna", city="Eskilstuna", address="Kungsgatan 66")),
    (5, 4, Venue(name="Biostaden Uddevalla", city="Uddevalla", address="Göteborgsvägen 11A")),
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


def _dates(payload: dict, venue: Venue) -> list[str]:
    days = sorted({date.fromisoformat(p["value"]).isoformat() for p in payload["dateOptions"] if p["value"] != "all"})
    if not days:
        raise ValueError(f"svenskabio: missing advertised dates for {venue.name}")
    return days


def _showtimes(
    payload: dict, day: str, venue: Venue, seen: set[str]
) -> Iterator[tuple[str, datetime, Film, Screening]]:
    cards = BeautifulSoup(payload["html"], "html.parser").select(_CARD)
    if payload["date"] != day or not cards:
        raise ValueError(f"svenskabio: missing advertised programme for {day}")
    for card in cards:
        when = datetime.fromisoformat(card.select_one(f"{_CARD}__time")["datetime"])
        booking = card.select_one(f"a{_CARD}__tickets[href]") or card.select_one(f"a{_CARD}__card-link[href]")
        if booking is None:
            raise ValueError(f"svenskabio: missing booking link for {venue.name} on {day}")
        wrapper = booking["href"]
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
        labels = {
            label.get_text(strip=True): label.parent.select_one(f"{_CARD}__label-text").get_text(strip=True)
            for label in card.select(f"{_CARD}__label .screen-reader-text")
        }
        yield (
            show_id,
            when,
            film,
            Screening(
                tmdb_id=None,
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
            ),
        )
