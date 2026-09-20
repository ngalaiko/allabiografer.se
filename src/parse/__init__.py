"""CLI entry point.

Usage::

    uv run parse --output data/allabiografer.db filmstaden_se
    uv run parse --output data/allabiografer.db bio_se

``--output`` is the SQLite database screenings, venues, movies, films and the
TMDB title index are written to.  Posters go to a ``posters/`` directory beside
it.
"""

import argparse
import importlib
import logging
import pkgutil
from pathlib import Path

import store
from parse import parsers
from parse.parsers import _films, _tmdb_cache
from store import Film, Screening, Venue

log = logging.getLogger(__name__)


def _available() -> list[str]:
    pkg_dir = str(Path(parsers.__file__).parent)
    return sorted(info.name for info in pkgutil.iter_modules([pkg_dir]) if not info.name.startswith("_"))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    names = _available()
    ap = argparse.ArgumentParser(prog="parse", description="Parse cinema screenings")
    ap.add_argument("parser", choices=names, help="Parser to run")
    ap.add_argument("--output", type=Path, default=store.DB_FILE, help="Output SQLite database (default: %(default)s)")
    args = ap.parse_args()

    _tmdb_cache.db_path = args.output
    _films.db_path = args.output

    mod = importlib.import_module(f"parse.parsers.{args.parser}")
    log.info("parser=%s starting", args.parser)

    screenings: list[Screening] = []
    venues: list[Venue] = []
    films: list[Film] = []
    for item in mod.parse():
        if isinstance(item, Venue):
            venues.append(item)
        elif isinstance(item, Film):
            films.append(item)
        else:
            screenings.append(item)

    n = store.write_screenings(screenings, path=args.output, source=args.parser, venues=venues)
    nv = store.write_venues(venues, path=args.output)
    nf = store.write_films(films, path=args.output)
    cities = len({s.city for s in screenings})
    cinemas = len({(s.city, s.cinema_name) for s in screenings})
    dates = len({s.date for s in screenings})
    log.info(
        "parser=%s done cities=%d cinemas=%d dates=%d screenings=%d venues=%d films=%d",
        args.parser,
        cities,
        cinemas,
        dates,
        n,
        nv,
        nf,
    )
