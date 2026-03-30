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
import re
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

_CSV_FIELDS = ["city", "cinema", "date", "time", "screen", "tmdb_id", "ticket_url", "format", "language", "subtitles"]


# ---------------------------------------------------------------------------
# Write helpers (used by parse)
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    text = text.strip()
    text = re.sub(r'[/\\:*?"<>|]', "_", text)
    return re.sub(r"\s+", " ", text)


def _screening_key(row: dict[str, str]) -> tuple[str, ...]:
    """Return a deduplication key for a screening CSV row."""
    return (row["city"], row["cinema"], row["date"], row["time"], row["tmdb_id"], row["ticket_url"])


def write_screenings(screenings: list[Screening], *, path: Path = SCREENINGS_FILE) -> int:
    """Merge screenings into the CSV file, deduplicating.  Returns count of new rows added.

    Uses file locking so multiple parsers can safely write in parallel.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")

    with open(lock_path, "w") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)

        seen_keys: set[tuple[str, ...]] = set()
        existing_rows: list[dict[str, str]] = []
        if path.exists() and path.stat().st_size > 0:
            with open(path, newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    key = _screening_key(row)
                    if key not in seen_keys:
                        existing_rows.append(row)
                        seen_keys.add(key)

        new_count = 0
        for s in screenings:
            row = {
                "city": s.city,
                "cinema": s.cinema_name,
                "date": s.date.isoformat(),
                "time": s.time.strftime("%H:%M"),
                "screen": s.screen,
                "tmdb_id": str(s.tmdb_id),
                "ticket_url": s.ticket_url,
                "format": s.format,
                "language": s.language,
                "subtitles": s.subtitles,
            }
            key = _screening_key(row)
            if key not in seen_keys:
                existing_rows.append(row)
                seen_keys.add(key)
                new_count += 1

        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerows(existing_rows)

    return new_count


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
                    tmdb_id=int(row["tmdb_id"]),
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
    out_dir = data_dir / _slugify(venue.city)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{_slugify(venue.name)}.json"
    with open(out_file, "w", encoding="utf-8") as fh:
        json.dump(venue.to_dict(), fh, ensure_ascii=False, indent=2)
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
