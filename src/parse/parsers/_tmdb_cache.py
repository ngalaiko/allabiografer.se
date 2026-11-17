"""Shared per-process TMDB title→id cache for parsers."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from parse import tmdb
from store import DB_FILE

log = logging.getLogger(__name__)

# Database every lookup writes to; the CLI points it at --output.
db_path: Path = DB_FILE

_cache: dict[tuple[str, int | None, int | None], int | None] = {}
_requests: ContextVar[dict[int, dict] | None] = ContextVar("tmdb_requests", default=None)


@contextmanager
def capture_requests() -> Iterator[dict[int, dict]]:
    """Defer title lookups as truthy negative tokens; explicit IDs pass through.

    Capture only the first branch of a parser's ``lookup(...) or lookup(...)``:
    without a TMDB result there is no evidence to justify relaxing runtime/year
    constraints (or trying a fallback title). Direct calls retain live lookups.
    Tokens are scoped to this context and must never be persisted as TMDB IDs.
    """
    requests: dict[int, dict] = {}
    token = _requests.set(requests)
    try:
        yield requests
    finally:
        _requests.reset(token)


def lookup(title: str, *, runtime: int | None = None, year: int | None = None) -> int | None:
    """Return TMDB id for *title*, or None.  Results are cached in-process.

    *year* restricts matches to that release year, e.g. for live broadcasts.
    """
    if (requests := _requests.get()) is not None:
        token = -(len(requests) + 1)
        requests[token] = {"title": title, "runtime": runtime, "year": year}
        return token
    key = (title, runtime, year)
    if key in _cache:
        return _cache[key]
    tmdb_id = tmdb.lookup(title, path=db_path, runtime=runtime, year=year)
    _cache[key] = tmdb_id
    if tmdb_id is None:
        log.debug("no TMDB match for %r", title)
    return tmdb_id


def by_id(tmdb_id: int) -> int | None:
    """Return *tmdb_id* once its metadata is stored, or None when the fetch fails."""
    if _requests.get() is not None:
        return tmdb_id
    return tmdb.by_id(tmdb_id, path=db_path)
