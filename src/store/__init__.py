"""Shared data store — the contract between ``parse`` and ``build``.

``parse`` writes screening data and movie metadata here.
``build`` reads them to produce the static site.

Tabular data lives in one SQLite file, ``data/allabiografer.db``::

    screenings  (city, cinema, date, time, screen, tmdb_id, ticket_url,
                 title, source, film_key, version, presentation, accessibility,
                 raw_attributes)
                 unique on showtime identity; structured facts are compact JSON
    movies      (tmdb_id PK, title_sv, title_original, overview_sv, genres,
                 release_date, release_date_se, runtime, poster_path,
                 vote_average, age_rating)
    films       (key PK, source, title, title_original, overview, runtime,
                 genres, release_date, age_rating, poster_url, url)
                 metadata from a cinema's own site, filling TMDB gaps
    venues      (city, name) PK, address
    tmdb_index  (key PK, tmdb_id) — title lookup cache
    festivals   (slug, year) PK, name, city, start, end, url, source
    festival_screenings
                (slug, year, id) PK, film and screening details;
                replaced per edition on each import

Poster images are files beside it, original bytes, keyed by TMDB id or by
film key::

    data/posters/{tmdb_id}.{jpg,png,webp,avif}
    data/posters/{source}/{title}.{jpg,png,webp,avif}

The directory is derived from the db path, so alternate db paths keep
their own posters.

Dates are ``YYYY-MM-DD``, times ``HH:MM``, genres a JSON array.
The file is committed to the repository, so the journal stays in DELETE
mode: no stray ``-wal``/``-shm`` siblings.
"""

import contextlib
import json
import os
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from store.festival import Festival, FestivalScreening
from store.film import Film, film_key, poster_key_for_film, title_key
from store.movie import Movie
from store.screening import Screening
from store.venue import Venue
from store.version import (
    Accessibility,
    AccessibilityFeature,
    AgeRating,
    AudioKind,
    AudioVersion,
    AuditoriumAttribute,
    ContentVersion,
    Dimension,
    Language,
    Presentation,
    PresentationSystem,
    ProjectionAttribute,
    ProjectionMedium,
    SoundAttribute,
    SubtitleVersion,
)

__all__ = [
    "DATA_DIR",
    "DB_FILE",
    "POSTERS_DIRNAME",
    "Accessibility",
    "AccessibilityFeature",
    "AgeRating",
    "AudioKind",
    "AudioVersion",
    "AuditoriumAttribute",
    "ContentVersion",
    "Dimension",
    "Festival",
    "FestivalScreening",
    "Film",
    "Language",
    "Movie",
    "Presentation",
    "PresentationSystem",
    "ProjectionAttribute",
    "ProjectionMedium",
    "Screening",
    "SoundAttribute",
    "SubtitleVersion",
    "Venue",
    "connect",
    "film_key",
    "has_poster",
    "poster_key_for_film",
    "poster_keys",
    "poster_path",
    "posters_dir",
    "read_all_films",
    "read_festivals",
    "read_film",
    "read_films",
    "read_movie",
    "read_movies",
    "read_poster",
    "read_screenings",
    "read_venues",
    "title_key",
    "tmdb_index_get",
    "tmdb_index_set",
    "write_festival",
    "write_films",
    "write_movie",
    "write_poster",
    "write_screenings",
    "write_venue",
    "write_venues",
]

DATA_DIR = Path("data")
DB_FILE = DATA_DIR / "allabiografer.db"
POSTERS_DIRNAME = "posters"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS screenings (
  city TEXT NOT NULL, cinema TEXT NOT NULL, date TEXT NOT NULL, time TEXT NOT NULL,
  screen TEXT NOT NULL DEFAULT '', tmdb_id INTEGER, ticket_url TEXT NOT NULL,
  version TEXT NOT NULL DEFAULT '{}', presentation TEXT NOT NULL DEFAULT '{}',
  accessibility TEXT NOT NULL DEFAULT '[]', raw_attributes TEXT NOT NULL DEFAULT '[]',
  title TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '', film_key TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS screenings_key
  ON screenings (city, cinema, date, time, screen, coalesce(tmdb_id, 0), title, ticket_url, source);
CREATE TABLE IF NOT EXISTS movies (
  tmdb_id INTEGER PRIMARY KEY, title_sv TEXT NOT NULL DEFAULT '', title_original TEXT NOT NULL DEFAULT '',
  overview_sv TEXT NOT NULL DEFAULT '', genres TEXT NOT NULL DEFAULT '[]', release_date TEXT NOT NULL DEFAULT '',
  release_date_se TEXT NOT NULL DEFAULT '', runtime INTEGER, poster_path TEXT NOT NULL DEFAULT '',
  vote_average REAL, age_rating TEXT NOT NULL DEFAULT '', original_language TEXT NOT NULL DEFAULT '',
  spoken_languages TEXT
);
CREATE TABLE IF NOT EXISTS films (
  key TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL,
  title_original TEXT NOT NULL DEFAULT '', overview TEXT NOT NULL DEFAULT '', runtime INTEGER,
  genres TEXT NOT NULL DEFAULT '[]', release_date TEXT NOT NULL DEFAULT '',
  age_rating TEXT NOT NULL DEFAULT '', poster_url TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '',
  original_languages TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS venues (
  city TEXT NOT NULL, name TEXT NOT NULL, address TEXT NOT NULL DEFAULT '', PRIMARY KEY (city, name)
);
CREATE TABLE IF NOT EXISTS tmdb_index (key TEXT PRIMARY KEY, tmdb_id INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS festivals (
  slug TEXT NOT NULL, year INTEGER NOT NULL, name TEXT NOT NULL, city TEXT NOT NULL,
  start TEXT NOT NULL, "end" TEXT NOT NULL, url TEXT NOT NULL, source TEXT NOT NULL,
  PRIMARY KEY (slug, year)
);
CREATE TABLE IF NOT EXISTS festival_screenings (
  slug TEXT NOT NULL, year INTEGER NOT NULL, id TEXT NOT NULL, film_id TEXT NOT NULL, title TEXT NOT NULL,
  start TEXT NOT NULL, "end" TEXT NOT NULL DEFAULT '', venue TEXT NOT NULL, url TEXT NOT NULL,
  language TEXT NOT NULL DEFAULT '', subtitles TEXT NOT NULL DEFAULT '', film_url TEXT NOT NULL DEFAULT '',
  poster_url TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', intro TEXT NOT NULL DEFAULT '',
  runtime INTEGER, genres TEXT NOT NULL DEFAULT '', sections TEXT NOT NULL DEFAULT '',
  director TEXT NOT NULL DEFAULT '', country TEXT NOT NULL DEFAULT '', production_year TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (slug, year, id),
  FOREIGN KEY (slug, year) REFERENCES festivals (slug, year) ON DELETE CASCADE
);
"""


def connect(path: Path = DB_FILE) -> sqlite3.Connection:
    """Open the database, creating the structured schema when missing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=600, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    existing_tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    app_tables = existing_tables & {
        "screenings",
        "films",
        "movies",
        "venues",
        "tmdb_index",
        "festivals",
        "festival_screenings",
    }
    if app_tables and "screenings" not in app_tables:
        conn.close()
        raise RuntimeError(
            f"Legacy database schema at {path}; remove it and reparse to rebuild structured screening data."
        )
    if "screenings" in existing_tables:
        screening_columns = {row[1] for row in conn.execute("PRAGMA table_info(screenings)")}
        film_columns = (
            {row[1] for row in conn.execute("PRAGMA table_info(films)")} if "films" in existing_tables else set()
        )
        required_screening = {"film_key", "version", "presentation", "accessibility", "raw_attributes"}
        if not required_screening <= screening_columns or "original_languages" not in film_columns:
            conn.close()
            raise RuntimeError(
                f"Legacy database schema at {path}; remove it and reparse to rebuild structured screening data."
            )
    try:
        conn.executescript(f"BEGIN IMMEDIATE;\n{_SCHEMA}\nCOMMIT;")
        movie_columns = {row[1] for row in conn.execute("PRAGMA table_info(movies)")}
        # Concurrent parsers may race to add these.
        if "original_language" not in movie_columns:
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute("ALTER TABLE movies ADD COLUMN original_language TEXT NOT NULL DEFAULT ''")
        if "spoken_languages" not in movie_columns:
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute("ALTER TABLE movies ADD COLUMN spoken_languages TEXT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()
        raise
    return conn


# ---------------------------------------------------------------------------
# Write helpers (used by parse)
# ---------------------------------------------------------------------------


_CITY_ALIASES: dict[str, str] = {
    # Stockholm municipality stadsdelar
    "Bromma": "Stockholm",
    "Älvsjö": "Stockholm",
    "Hägersten": "Stockholm",
    "Johanneshov": "Stockholm",
    "Midsommarkransen": "Stockholm",
    "Skärholmen": "Stockholm",
    "Spånga": "Stockholm",
    "Årsta": "Stockholm",
    # Göteborg municipality stadsdelar
    "Angered": "Göteborg",
    "Torslanda": "Göteborg",
    "Västra Frölunda": "Göteborg",
}


def _normalize_city(city: str) -> str:
    return _CITY_ALIASES.get(city, city)


def write_screenings(
    screenings: list[Screening],
    *,
    path: Path = DB_FILE,
    source: str = "",
    venues: list[Venue] = (),
    replaces_sources: tuple[str, ...] = (),
) -> int:
    """Replace a source snapshot after a complete parse.  Returns rows added.

    Unowned legacy rows migrate only for venues covered by this snapshot.
    Named replaced sources are removed in the same transaction.
    Other sources remain intact. Calls without a source merge records.
    """
    covered = {(_normalize_city(v.city), v.name) for v in venues}
    covered.update((_normalize_city(s.city), s.cinema_name) for s in screenings)
    rows = [
        (
            _normalize_city(s.city),
            s.cinema_name,
            s.date.isoformat(),
            s.time.strftime("%H:%M"),
            s.screen,
            s.tmdb_id,
            s.ticket_url,
            s.title,
            source or s.source,
            s.film_key,
            json.dumps(s.to_dict()["version"], ensure_ascii=False),
            json.dumps(s.to_dict()["presentation"], ensure_ascii=False),
            json.dumps(s.to_dict()["accessibility"], ensure_ascii=False),
            json.dumps(s.to_dict()["raw_attributes"], ensure_ascii=False),
        )
        for s in screenings
    ]
    conn = connect(path)
    try:
        # One immediate transaction so parallel parsers serialise.
        conn.execute("BEGIN IMMEDIATE")
        if source:
            conn.executemany("DELETE FROM screenings WHERE source = ?", [(s,) for s in (source, *replaces_sources)])
            # Keep separate source ownership even when public listings overlap.
            conn.executemany(
                "DELETE FROM screenings WHERE source = '' AND city = ? AND cinema = ?",
                sorted(covered),
            )
        added = 0
        for row in rows:
            cur = conn.execute(
                "INSERT OR IGNORE INTO screenings"
                " (city, cinema, date, time, screen, tmdb_id, ticket_url,"
                "  title, source, film_key, version,"
                "  presentation, accessibility, raw_attributes)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
            added += cur.rowcount
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return added


# ---------------------------------------------------------------------------
# Read helpers (used by build)
# ---------------------------------------------------------------------------


def read_screenings(*, path: Path = DB_FILE) -> list[Screening]:
    """Read all screenings in insertion order."""
    conn = connect(path)
    try:
        rows = conn.execute(
            "SELECT city, cinema, date, time, screen, tmdb_id, ticket_url,"
            " version, presentation, accessibility, raw_attributes, title, source, film_key"
            " FROM screenings ORDER BY rowid"
        ).fetchall()
    finally:
        conn.close()
    results = []
    for row in rows:
        (
            city,
            cinema,
            day,
            clock,
            screen,
            tmdb_id,
            ticket_url,
            version,
            presentation,
            accessibility,
            raw_attributes,
            title,
            source,
            film,
        ) = row
        results.append(
            Screening.from_dict(
                {
                    "tmdb_id": tmdb_id,
                    "title": title,
                    "source": source,
                    "film_key": film,
                    "date": day,
                    "time": clock,
                    "ticket_url": ticket_url,
                    "cinema_name": cinema,
                    "city": city,
                    "screen": screen,
                    "version": json.loads(version),
                    "presentation": json.loads(presentation),
                    "accessibility": json.loads(accessibility),
                    "raw_attributes": json.loads(raw_attributes),
                }
            )
        )
    return results


# ---------------------------------------------------------------------------
# Movies
# ---------------------------------------------------------------------------

_MOVIE_COLUMNS = (
    "tmdb_id",
    "title_sv",
    "title_original",
    "overview_sv",
    "genres",
    "release_date",
    "release_date_se",
    "runtime",
    "poster_path",
    "vote_average",
    "age_rating",
    "original_language",
    "spoken_languages",
)


def _movie_from_row(row: tuple) -> Movie:
    d = dict(zip(_MOVIE_COLUMNS, row, strict=True))
    d["genres"] = json.loads(d["genres"])
    if d["spoken_languages"] is not None:
        d["spoken_languages"] = json.loads(d["spoken_languages"])
    return Movie.from_dict(d)


def read_movie(tmdb_id: int, *, path: Path = DB_FILE) -> Movie | None:
    """Read movie metadata for a TMDB id.  Returns None if not found."""
    conn = connect(path)
    try:
        row = conn.execute(
            f"SELECT {', '.join(_MOVIE_COLUMNS)} FROM movies WHERE tmdb_id = ?",
            (tmdb_id,),
        ).fetchone()
    finally:
        conn.close()
    return _movie_from_row(row) if row else None


def read_movies(tmdb_ids: Iterable[int], *, path: Path = DB_FILE) -> dict[int, Movie]:
    """Read movie metadata for many TMDB ids.  Missing ids are absent."""
    ids = list(tmdb_ids)
    if not ids:
        return {}
    conn = connect(path)
    try:
        result = {}
        # Chunked to stay under SQLite's variable limit.
        for start in range(0, len(ids), 500):
            chunk = ids[start : start + 500]
            placeholders = ", ".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT {', '.join(_MOVIE_COLUMNS)} FROM movies WHERE tmdb_id IN ({placeholders})",
                chunk,
            ).fetchall()
            for row in rows:
                movie = _movie_from_row(row)
                result[movie.tmdb_id] = movie
    finally:
        conn.close()
    return result


def write_movie(movie: Movie, *, path: Path = DB_FILE) -> None:
    """Upsert movie metadata."""
    conn = connect(path)
    try:
        conn.execute(
            "INSERT INTO movies"
            " (tmdb_id, title_sv, title_original, overview_sv, genres, release_date,"
            "  release_date_se, runtime, poster_path, vote_average, age_rating, original_language,"
            "  spoken_languages)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (tmdb_id) DO UPDATE SET"
            "  title_sv = excluded.title_sv, title_original = excluded.title_original,"
            "  overview_sv = excluded.overview_sv, genres = excluded.genres,"
            "  release_date = excluded.release_date, release_date_se = excluded.release_date_se,"
            "  runtime = excluded.runtime, poster_path = excluded.poster_path,"
            "  vote_average = excluded.vote_average, age_rating = excluded.age_rating,"
            "  original_language = excluded.original_language, spoken_languages = excluded.spoken_languages",
            (
                movie.tmdb_id,
                movie.title_sv or "",
                movie.title_original or "",
                movie.overview_sv or "",
                json.dumps(movie.genres or [], ensure_ascii=False),
                movie.release_date or "",
                movie.release_date_se or "",
                movie.runtime,
                movie.poster_path or "",
                movie.vote_average,
                movie.age_rating or "",
                movie.original_language or "",
                None if movie.spoken_languages is None else json.dumps(movie.spoken_languages),
            ),
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Films — metadata from the cinema sites themselves
# ---------------------------------------------------------------------------

_FILM_COLUMNS = (
    "key",
    "source",
    "title",
    "title_original",
    "overview",
    "runtime",
    "genres",
    "release_date",
    "age_rating",
    "poster_url",
    "url",
    "original_languages",
)


def _film_from_row(row: tuple) -> Film:
    d = dict(zip(_FILM_COLUMNS, row, strict=True))
    d["genres"] = json.loads(d["genres"])
    d["original_languages"] = json.loads(d["original_languages"])
    return Film.from_dict(d)


def read_film(key: str, *, path: Path = DB_FILE) -> Film | None:
    """Read site metadata for a film key.  Returns None if not found."""
    conn = connect(path)
    try:
        row = conn.execute(
            f"SELECT {', '.join(_FILM_COLUMNS)} FROM films WHERE key = ?",
            (key,),
        ).fetchone()
    finally:
        conn.close()
    return _film_from_row(row) if row else None


def read_films(keys: Iterable[str], *, path: Path = DB_FILE) -> dict[str, Film]:
    """Read site metadata for many film keys.  Missing keys are absent."""
    wanted = list(keys)
    if not wanted:
        return {}
    conn = connect(path)
    try:
        result = {}
        # Chunked to stay under SQLite's variable limit.
        for start in range(0, len(wanted), 500):
            chunk = wanted[start : start + 500]
            placeholders = ", ".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT {', '.join(_FILM_COLUMNS)} FROM films WHERE key IN ({placeholders})",
                chunk,
            ).fetchall()
            for row in rows:
                film = _film_from_row(row)
                result[film.key] = film
    finally:
        conn.close()
    return result


def read_all_films(*, path: Path = DB_FILE) -> list[Film]:
    """Read every stored film, ordered by key."""
    conn = connect(path)
    try:
        rows = conn.execute(f"SELECT {', '.join(_FILM_COLUMNS)} FROM films ORDER BY key").fetchall()
    finally:
        conn.close()
    return [_film_from_row(row) for row in rows]


def write_films(films: list[Film], *, path: Path = DB_FILE) -> int:
    """Upsert films by key.  Returns count."""
    conn = connect(path)
    try:
        conn.executemany(
            "INSERT INTO films"
            " (key, source, title, title_original, overview, runtime, genres,"
            "  release_date, age_rating, poster_url, url, original_languages)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (key) DO UPDATE SET"
            "  source = excluded.source, title = excluded.title,"
            "  title_original = excluded.title_original, overview = excluded.overview,"
            "  runtime = excluded.runtime, genres = excluded.genres,"
            "  release_date = excluded.release_date, age_rating = excluded.age_rating,"
            "  poster_url = excluded.poster_url, url = excluded.url,"
            "  original_languages = excluded.original_languages",
            [
                (
                    f.key,
                    f.source,
                    f.title,
                    f.title_original,
                    f.overview,
                    f.runtime,
                    json.dumps(f.genres or [], ensure_ascii=False),
                    f.release_date,
                    f.age_rating,
                    f.poster_url,
                    f.url,
                    json.dumps(sorted(language.value for language in f.original_languages), ensure_ascii=False),
                )
                for f in films
            ],
        )
    finally:
        conn.close()
    return len(films)


# ---------------------------------------------------------------------------
# Posters — files in ``posters/`` beside the db
# ---------------------------------------------------------------------------

_POSTER_EXTS = (".jpg", ".png", ".webp", ".avif")
_CONTENT_TYPE_EXTS = {"image/png": ".png", "image/webp": ".webp", "image/avif": ".avif"}


def posters_dir(path: Path = DB_FILE) -> Path:
    """Poster directory for a db path."""
    return path.parent / POSTERS_DIRNAME


def poster_path(key: str | int, *, path: Path = DB_FILE) -> Path | None:
    """Path of the stored poster file, or None when absent."""
    directory = posters_dir(path)
    for ext in _POSTER_EXTS:
        candidate = directory / f"{key}{ext}"
        if candidate.exists():
            return candidate
    return None


def read_poster(key: str | int, *, path: Path = DB_FILE) -> bytes | None:
    """Return poster image bytes, or None when absent."""
    found = poster_path(key, path=path)
    return found.read_bytes() if found else None


def has_poster(key: str | int, *, path: Path = DB_FILE) -> bool:
    """Whether a poster is stored under this key."""
    return poster_path(key, path=path) is not None


def poster_keys(*, path: Path = DB_FILE) -> set[str]:
    """All keys with a stored poster — paths relative to the posters dir, without suffix."""
    directory = posters_dir(path)
    if not directory.is_dir():
        return set()
    return {
        f.relative_to(directory).with_suffix("").as_posix()
        for f in directory.rglob("*")
        if f.suffix in _POSTER_EXTS and not f.name.startswith(".")
    }


def write_poster(key: str | int, data: bytes, content_type: str, *, path: Path = DB_FILE) -> Path:
    """Write a poster image, replacing any earlier one for this key."""
    ext = _CONTENT_TYPE_EXTS.get(content_type, ".jpg")
    directory = posters_dir(path)
    dest = directory / f"{key}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.name}.tmp"
    tmp.write_bytes(data)
    os.replace(tmp, dest)
    for other in _POSTER_EXTS:
        if other != ext:
            (directory / f"{key}{other}").unlink(missing_ok=True)
    return dest


# ---------------------------------------------------------------------------
# Venues
# ---------------------------------------------------------------------------


def write_venue(venue: Venue, *, path: Path = DB_FILE) -> None:
    """Upsert venue metadata."""
    write_venues([venue], path=path)


def write_venues(venues: list[Venue], *, path: Path = DB_FILE) -> int:
    """Upsert venues.  Returns count."""
    conn = connect(path)
    try:
        conn.executemany(
            "INSERT INTO venues (city, name, address) VALUES (?, ?, ?)"
            " ON CONFLICT (city, name) DO UPDATE SET address = excluded.address",
            [(_normalize_city(v.city), v.name, v.address) for v in venues],
        )
    finally:
        conn.close()
    return len(venues)


def read_venues(*, path: Path = DB_FILE) -> list[Venue]:
    """Read all venues."""
    conn = connect(path)
    try:
        rows = conn.execute("SELECT city, name, address FROM venues ORDER BY city, name").fetchall()
    finally:
        conn.close()
    return [Venue(city=city, name=name, address=address) for city, name, address in rows]


# ---------------------------------------------------------------------------
# TMDB title → id index
# ---------------------------------------------------------------------------


def tmdb_index_get(key: str, *, path: Path = DB_FILE) -> int | None:
    """Look up a cached TMDB id by index key."""
    conn = connect(path)
    try:
        row = conn.execute("SELECT tmdb_id FROM tmdb_index WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def tmdb_index_set(key: str, tmdb_id: int, *, path: Path = DB_FILE) -> None:
    """Cache a TMDB id under an index key."""
    conn = connect(path)
    try:
        conn.execute(
            "INSERT INTO tmdb_index (key, tmdb_id) VALUES (?, ?)"
            " ON CONFLICT (key) DO UPDATE SET tmdb_id = excluded.tmdb_id",
            (key, tmdb_id),
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Festivals
# ---------------------------------------------------------------------------

_FESTIVAL_COLUMNS = ("slug", "year", "name", "city", "start", "end", "url", "source")
_FESTIVAL_SCREENING_COLUMNS = (
    "id",
    "film_id",
    "title",
    "start",
    "end",
    "venue",
    "url",
    "language",
    "subtitles",
    "film_url",
    "poster_url",
    "description",
    "intro",
    "runtime",
    "genres",
    "sections",
    "director",
    "country",
    "production_year",
)


def _columns(names: Iterable[str]) -> str:
    return ", ".join(f'"{name}"' for name in names)


def write_festival(festival: Festival, screenings: list[FestivalScreening], *, path: Path = DB_FILE) -> int:
    """Upsert an edition and replace its screenings.  Returns count."""
    conn = connect(path)
    try:
        conn.execute("BEGIN")
        conn.execute(
            f"INSERT INTO festivals ({_columns(_FESTIVAL_COLUMNS)}) VALUES ({', '.join('?' * len(_FESTIVAL_COLUMNS))})"
            " ON CONFLICT (slug, year) DO UPDATE SET"
            + ", ".join(f' "{c}" = excluded."{c}"' for c in _FESTIVAL_COLUMNS[2:]),
            tuple(getattr(festival, c) for c in _FESTIVAL_COLUMNS),
        )
        conn.execute("DELETE FROM festival_screenings WHERE slug = ? AND year = ?", (festival.slug, festival.year))
        conn.executemany(
            f"INSERT INTO festival_screenings (slug, year, {_columns(_FESTIVAL_SCREENING_COLUMNS)})"
            f" VALUES ({', '.join('?' * (len(_FESTIVAL_SCREENING_COLUMNS) + 2))})",
            [(festival.slug, festival.year, *(getattr(s, c) for c in _FESTIVAL_SCREENING_COLUMNS)) for s in screenings],
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return len(screenings)


def read_festivals(*, path: Path = DB_FILE) -> list[tuple[Festival, list[FestivalScreening]]]:
    """Read every edition with its screenings, by slug and year."""
    conn = connect(path)
    try:
        festivals = conn.execute(f"SELECT {_columns(_FESTIVAL_COLUMNS)} FROM festivals ORDER BY slug, year").fetchall()
        rows = conn.execute(
            f"SELECT slug, year, {_columns(_FESTIVAL_SCREENING_COLUMNS)} FROM festival_screenings ORDER BY start, id"
        ).fetchall()
    finally:
        conn.close()
    screenings: dict[tuple[str, int], list[FestivalScreening]] = {}
    for slug, year, *values in rows:
        screenings.setdefault((slug, year), []).append(
            FestivalScreening(**dict(zip(_FESTIVAL_SCREENING_COLUMNS, values, strict=True)))
        )
    return [
        (Festival(**dict(zip(_FESTIVAL_COLUMNS, row, strict=True))), screenings.get((row[0], row[1]), []))
        for row in festivals
    ]
