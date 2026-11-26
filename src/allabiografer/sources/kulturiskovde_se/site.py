"""Skövde Kulturhus's public cinema programmes, from its linked Tix listings."""

from datetime import date, time

from allabiografer.model import Venue

_VENUE = Venue(name="Biograf Odeon", city="Skövde", address="Trädgårdsgatan 9")
_SERIES = (31841, 31784)
_MONTHS = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]


def _showtimes(soup):
    for row in soup.select('tr.event-select[data-pro="Skövde Kulturhus"]'):
        title, hall, local_date, local_time = (
            row.select_one(f"td.{field}") for field in ("name", "location", "date", "time")
        )
        if not (title and hall and local_date and local_time) or hall.get_text(strip=True) != "Odeon":
            continue
        _, day, month, year = local_date.get_text(" ", strip=True).split()
        yield (
            row.get("data-value"),
            title.get_text(strip=True),
            date(int(year), _MONTHS.index(month) + 1, int(day)),
            time.fromisoformat(local_time.get_text(strip=True)),
        )
