"""CLI entry point.

Usage::

    uv run parse --output data filmstaden_se
    uv run parse --output data bio_se
"""

import argparse
import importlib
import logging
import pkgutil
from pathlib import Path

import store
from parse import parsers
from store import Screening, Venue

log = logging.getLogger(__name__)


def _available() -> list[str]:
    pkg_dir = str(Path(parsers.__file__).parent)
    return sorted(info.name for info in pkgutil.iter_modules([pkg_dir]) if not info.name.startswith("_"))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    names = _available()
    ap = argparse.ArgumentParser(prog="parse", description="Parse cinema screenings")
    ap.add_argument("parser", choices=names, help="Parser to run")
    ap.add_argument("--output", type=Path, default=store.SCREENINGS_FILE, help="Output CSV file (default: %(default)s)")
    args = ap.parse_args()

    mod = importlib.import_module(f"parse.parsers.{args.parser}")
    log.info("parser=%s starting", args.parser)

    screenings: list[Screening] = []
    venues: list[Venue] = []
    for item in mod.parse():
        if isinstance(item, Venue):
            venues.append(item)
        else:
            screenings.append(item)

    n = store.write_screenings(screenings, path=args.output)
    nv = store.write_venues(venues)
    cities = len({s.city for s in screenings})
    cinemas = len({(s.city, s.cinema_name) for s in screenings})
    dates = len({s.date for s in screenings})
    log.info(
        "parser=%s done cities=%d cinemas=%d dates=%d screenings=%d venues=%d",
        args.parser,
        cities,
        cinemas,
        dates,
        n,
        nv,
    )
