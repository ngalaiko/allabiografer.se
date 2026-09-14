"""Shared per-process TMDB title→id cache for parsers."""

import logging

from parse import tmdb
from store import MOVIES_DIR

log = logging.getLogger(__name__)

_cache: dict[tuple[str, int | None], int | None] = {}


def lookup(title: str, *, runtime: int | None = None) -> int | None:
    """Return TMDB id for *title*, or None.  Results are cached in-process."""
    key = (title, runtime)
    if key in _cache:
        return _cache[key]
    tmdb_id = tmdb.lookup(title, movies_dir=MOVIES_DIR, runtime=runtime)
    _cache[key] = tmdb_id
    if tmdb_id is None:
        log.debug("no TMDB match for %r", title)
    return tmdb_id
