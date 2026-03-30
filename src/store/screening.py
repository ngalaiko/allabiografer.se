"""The Screening value object."""

from dataclasses import dataclass
from datetime import date, time
from typing import Self


@dataclass(frozen=True, slots=True, kw_only=True)
class Screening:
    """One showtime of one film at one cinema."""

    tmdb_id: int
    date: date
    time: time
    ticket_url: str
    cinema_name: str
    city: str

    # optional
    screen: str = ""
    format: str = ""
    language: str = ""
    subtitles: str = ""

    def to_dict(self) -> dict[str, str | int]:
        """Serialise for JSON storage."""
        d: dict[str, str | int] = {
            "tmdb_id": self.tmdb_id,
            "date": self.date.isoformat(),
            "time": self.time.strftime("%H:%M"),
            "cinema_name": self.cinema_name,
            "city": self.city,
            "ticket_url": self.ticket_url,
        }
        for key in ("screen", "format", "language", "subtitles"):
            val = getattr(self, key)
            if val:
                d[key] = val
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Self:
        """Deserialise from JSON storage."""
        h, m = d["time"].split(":")
        return cls(
            tmdb_id=d["tmdb_id"],
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
