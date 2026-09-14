"""Shared data store — the contract between ``parse`` and ``build``.

``parse`` writes screening data and movie metadata here.
``build`` reads them to produce the static site.

Layout::

    data/screenings.csv
    data/movies/{tmdb_id}.json
    data/movies/{tmdb_id}.w500.jpg
    data/venues/{City}/{Venue}.json
"""

import csv
import fcntl
import json
import os
import re
import tempfile
from datetime import date, time
from pathlib import Path

from store.movie import Movie
from store.screening import Screening
from store.venue import Venue

__all__ = ["DATA_DIR", "MOVIES_DIR", "SCREENINGS_FILE", "VENUES_DIR", "Movie", "Screening", "Venue"]

DATA_DIR = Path("data")
SCREENINGS_FILE = DATA_DIR / "screenings.csv"
MOVIES_DIR = DATA_DIR / "movies"
VENUES_DIR = DATA_DIR / "venues"

_CSV_FIELDS = [
    "city",
    "cinema",
    "date",
    "time",
    "screen",
    "tmdb_id",
    "ticket_url",
    "format",
    "language",
    "subtitles",
    "title",
    "source",
]


# ---------------------------------------------------------------------------
# Write helpers (used by parse)
# ---------------------------------------------------------------------------


_CITY_ALIASES: dict[str, str] = {
    # Stockholm municipality stadsdelar
    "Bromma": "Stockholm",
    "Älvsjö": "Stockholm",
    "Hägersten": "Stockholm",
    "Johanneshov": "Stockholm",
    "Skärholmen": "Stockholm",
    "Årsta": "Stockholm",
    # Göteborg municipality stadsdelar
    "Angered": "Göteborg",
    "Torslanda": "Göteborg",
    "Västra Frölunda": "Göteborg",
}


def _normalize_city(city: str) -> str:
    return _CITY_ALIASES.get(city, city)


def _slugify(text: str) -> str:
    text = text.strip()
    text = re.sub(r'[/\\:*?"<>|]', "_", text)
    return re.sub(r"\s+", " ", text)


def _screening_key(row: dict[str, str]) -> tuple[str, ...]:
    """Return a deduplication key for a screening CSV row."""
    return (
        row["city"],
        row["cinema"],
        row["date"],
        row["time"],
        row.get("screen", ""),
        row["tmdb_id"],
        row.get("title", ""),
        row["ticket_url"],
        row.get("source", ""),
    )


def write_screenings(
    screenings: list[Screening],
    *,
    path: Path = SCREENINGS_FILE,
    source: str = "",
    venues: list[Venue] = (),
) -> int:
    """Atomically replace a source snapshot after a complete parse.

    Unowned legacy rows migrate only for venues covered by this snapshot.
    Other sources remain intact. Calls without a source merge records.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    covered = {(_normalize_city(v.city), v.name) for v in venues}
    covered.update((_normalize_city(s.city), s.cinema_name) for s in screenings)
    with open(path.with_suffix(".lock"), "w") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        rows = []
        if path.exists():
            with open(path, newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    owned = row.get("source") == source
                    legacy = not row.get("source") and (row["city"], row["cinema"]) in covered
                    if source and (owned or legacy):
                        continue
                    rows.append(row)
        seen = {_screening_key(row) for row in rows}
        added = 0
        for screening in screenings:
            row = {key: str(value) if value is not None else "" for key, value in screening.to_dict().items()}
            row["cinema"] = row.pop("cinema_name")
            row["city"] = _normalize_city(screening.city)
            row["source"] = source or screening.source
            key = _screening_key(row)
            if key not in seen:
                rows.append(row)
                seen.add(key)
                added += 1
        # Keep separate source ownership even when public listings overlap.
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, newline="", encoding="utf-8") as fh:
            temporary = Path(fh.name)
            try:
                writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
                fh.flush()
                os.fsync(fh.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
    return added


# ---------------------------------------------------------------------------
# Read helpers (used by build)
# ---------------------------------------------------------------------------


def read_screenings(*, path: Path = SCREENINGS_FILE) -> list[Screening]:
    """Read all screenings from the CSV file."""
    if not path.exists():
        return []
    results = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            h, m = row["time"].split(":")
            results.append(
                Screening(
                    tmdb_id=int(row["tmdb_id"]) if row["tmdb_id"] else None,
                    title=row.get("title", ""),
                    source=row.get("source", ""),
                    date=date.fromisoformat(row["date"]),
                    time=time(int(h), int(m)),
                    ticket_url=row["ticket_url"],
                    cinema_name=row["cinema"],
                    city=row["city"],
                    screen=row.get("screen", ""),
                    format=row.get("format", ""),
                    language=row.get("language", ""),
                    subtitles=row.get("subtitles", ""),
                )
            )
    return results


def read_movie(tmdb_id: int, *, movies_dir: Path = MOVIES_DIR) -> Movie | None:
    """Read movie metadata for a TMDB id.  Returns None if not found."""
    p = movies_dir / f"{tmdb_id}.json"
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as fh:
        return Movie.from_dict(json.load(fh))


def movie_poster_path(tmdb_id: int, *, movies_dir: Path = MOVIES_DIR) -> Path | None:
    """Return path to poster image if it exists."""
    for ext in (".w500.jpg", ".w500.png", ".w500.webp"):
        p = movies_dir / f"{tmdb_id}{ext}"
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Venue helpers
# ---------------------------------------------------------------------------


def write_venue(venue: Venue, *, data_dir: Path = VENUES_DIR) -> Path:
    """Write venue metadata JSON.  Returns the written path."""
    city = _normalize_city(venue.city)
    out_dir = data_dir / _slugify(city)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{_slugify(venue.name)}.json"
    payload = venue.to_dict()
    payload["city"] = city
    with open(out_file, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return out_file


def write_venues(venues: list[Venue], *, data_dir: Path = VENUES_DIR) -> int:
    """Write each venue as a JSON file.  Returns count."""
    for v in venues:
        write_venue(v, data_dir=data_dir)
    return len(venues)


def read_venues(*, data_dir: Path = VENUES_DIR) -> list[Venue]:
    """Read all venue JSON files."""
    results = []
    if not data_dir.exists():
        return results
    for p in data_dir.rglob("*.json"):
        with open(p, encoding="utf-8") as fh:
            results.append(Venue.from_dict(json.load(fh)))
    return results
