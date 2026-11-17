"""Deferred TMDB query hints, owned and replaced independently per source.

Queries retain the parser's exact title/runtime/year constraints. Their order is
first use in emitted screenings, with identical queries deduplicated per film.
Only the CLI's successful nonempty fetches replace hints; an empty replacement
mapping clears that source's obsolete hints without affecting any other source.
"""

import json
from pathlib import Path

import store

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tmdb_requests (
    source TEXT NOT NULL,
    film_key TEXT NOT NULL,
    queries TEXT NOT NULL,
    PRIMARY KEY (source, film_key)
)
"""


def write_requests(requests: dict[str, list[dict]], *, source: str, path: Path = store.DB_FILE) -> None:
    """Atomically replace one source's hints, preserving every other source."""
    conn = store.connect(path)
    try:
        conn.execute(_SCHEMA)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM tmdb_requests WHERE source = ?", (source,))
        conn.executemany(
            "INSERT INTO tmdb_requests (source, film_key, queries) VALUES (?, ?, ?)",
            [(source, key, json.dumps(queries, ensure_ascii=False)) for key, queries in requests.items()],
        )
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def read_requests(*, path: Path = store.DB_FILE) -> dict[str, list[dict]]:
    """Return source film keys mapped to ordered title/runtime/year queries."""
    conn = store.connect(path)
    try:
        conn.execute(_SCHEMA)
        rows = conn.execute("SELECT film_key, queries FROM tmdb_requests ORDER BY source, film_key").fetchall()
    finally:
        conn.close()
    result: dict[str, list[dict]] = {}
    for key, queries in rows:
        values = result.setdefault(key, [])
        for query in json.loads(queries):
            if query not in values:
                values.append(query)
    return result
