"""Shared per-process TMDB title→id cache for parsers."""

import logging
from pathlib import Path

from parse import tmdb
from store import DB_FILE

log = logging.getLogger(__name__)

# Database every lookup writes to; the CLI points it at --output.
db_path: Path = DB_FILE

_cache: dict[tuple[str, int | None], int | None] = {}


def lookup(title: str, *, runtime: int | None = None) -> int | None:
    """Return TMDB id for *title*, or None.  Results are cached in-process."""
    key = (title, runtime)
    if key in _cache:
        return _cache[key]
    tmdb_id = tmdb.lookup(title, path=db_path, runtime=runtime)
    _cache[key] = tmdb_id
    if tmdb_id is None:
        log.debug("no TMDB match for %r", title)
    return tmdb_id
