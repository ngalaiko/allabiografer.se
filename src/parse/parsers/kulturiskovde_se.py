"""Skövde Kulturhus's public cinema programmes, from its linked Tix listings."""

from collections.abc import Iterator
from datetime import date, time

from bs4 import BeautifulSoup

from parse import _http
from parse.parsers import _films
from store import Film, Screening, Venue
from store.version import Presentation, PresentationSystem

_SOURCE = "kulturiskovde_se"
_VENUE = Venue(name="Biograf Odeon", city="Skövde", address="Trädgårdsgatan 9")
_SERIES = {31841: PresentationSystem.CHILDRENS_CINEMA, 31784: None}
_MONTHS = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]


def parse() -> Iterator[Screening | Venue | Film]:
    yield _VENUE
    with _http.session() as session:
        for series, label in _SERIES.items():
            url = f"https://tix.se/sv/skovde/buyingflow/tickets/{series}/"
            response = session.get(url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser", from_encoding="utf-8")
            for row in soup.select('tr.event-select[data-pro="Skövde Kulturhus"]'):
                title, hall, local_date, local_time = (
                    row.select_one(f"td.{field}") for field in ("name", "location", "date", "time")
                )
                if not (title and hall and local_date and local_time) or hall.get_text(strip=True) != "Odeon":
                    continue
                _, day, month, year = local_date.get_text(" ", strip=True).split()
                film = _films.make(_SOURCE, title.get_text(strip=True))
                yield film
                yield Screening(
                    tmdb_id=None,
                    title=film.title,
                    source=_SOURCE,
                    film_key=film.key,
                    date=date(int(year), _MONTHS.index(month) + 1, int(day)),
                    time=time.fromisoformat(local_time.get_text(strip=True)),
                    city=_VENUE.city,
                    cinema_name=_VENUE.name,
                    screen="Odeon",
                    ticket_url=url,
                    presentation=Presentation(experiences=frozenset({label}) if label else frozenset()),
                )
