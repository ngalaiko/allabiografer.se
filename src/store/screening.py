"""The Screening value object."""

from dataclasses import dataclass
from datetime import date, time
from typing import Self


@dataclass(frozen=True, slots=True, kw_only=True)
class Screening:
    """One showtime of one film at one cinema."""

    tmdb_id: int | None
    date: date
    time: time
    ticket_url: str
    cinema_name: str
    city: str

    # optional
    title: str = ""
    source: str = ""
    film_key: str = ""
    screen: str = ""
    format: str = ""
    language: str = ""
    subtitles: str = ""

    def to_dict(self) -> dict[str, str | int | None]:
        """Serialise for JSON storage."""
        d: dict[str, str | int | None] = {
            "tmdb_id": self.tmdb_id,
            "date": self.date.isoformat(),
            "time": self.time.strftime("%H:%M"),
            "cinema_name": self.cinema_name,
            "city": self.city,
            "ticket_url": self.ticket_url,
        }
        for key in ("title", "source", "film_key", "screen", "format", "language", "subtitles"):
            val = getattr(self, key)
            if val:
                d[key] = val
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Self:
        """Deserialise from JSON storage."""
        h, m = d["time"].split(":")
        return cls(
            tmdb_id=d.get("tmdb_id"),
            title=d.get("title", ""),
            source=d.get("source", ""),
            film_key=d.get("film_key", ""),
            date=date.fromisoformat(d["date"]),
            time=time(int(h), int(m)),
            ticket_url=d["ticket_url"],
            cinema_name=d["cinema_name"],
            city=d["city"],
            screen=d.get("screen", ""),
            format=d.get("format", ""),
            language=d.get("language", ""),
            subtitles=d.get("subtitles", ""),
        )
