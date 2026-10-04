"""CLI entry point.

Usage::

    uv run parse --output data/allabiografer.db filmstaden_se
    uv run parse --output data/allabiografer.db bio_se

``--output`` is the SQLite database screenings, venues, movies, films and the
TMDB title index are written to.  Posters go to a ``posters/`` directory beside
it.
"""

import argparse
import dataclasses
import importlib
import logging
import pkgutil
from collections.abc import Iterable, Mapping
from pathlib import Path

import store
from parse import parsers, tmdb
from parse.parsers import _films, _tmdb_cache
from store import Film, Screening, Venue
from store.version import AudioKind, AudioVersion, Language

log = logging.getLogger(__name__)


def _available() -> list[str]:
    pkg_dir = str(Path(parsers.__file__).parent)
    return sorted(info.name for info in pkgutil.iter_modules([pkg_dir]) if not info.name.startswith("_"))


# Languages counted as one when comparing audio with the original.
_FAMILY = {Language.MANDARIN: Language.CHINESE, Language.CANTONESE: Language.CHINESE}


def _families(languages: frozenset[Language]) -> frozenset[Language]:
    return frozenset(_FAMILY.get(language, language) for language in languages)


def mark_dubbed(
    screenings: Iterable[Screening],
    films: Iterable[Film],
    tmdb_languages: Mapping[int, frozenset[Language]] | None = None,
) -> list[Screening]:
    """Mark audio of unknown kind dubbed when none of its languages is an original language of the film.

    TMDB's original and spoken languages win over the site's; site languages apply when TMDB has none.
    """
    originals = {f.key: f.original_languages for f in films}
    tmdb_languages = tmdb_languages or {}
    result = []
    for s in screenings:
        audio = s.version.audio
        original = (s.tmdb_id is not None and tmdb_languages.get(s.tmdb_id)) or originals.get(s.film_key)
        if (
            audio.kind is AudioKind.UNKNOWN
            and audio.languages
            and original
            and not _families(audio.languages) & _families(original)
        ):
            version = dataclasses.replace(s.version, audio=AudioVersion(AudioKind.DUBBED, audio.languages))
            s = dataclasses.replace(s, version=version)
        result.append(s)
    return result


def tmdb_languages(screenings: Iterable[Screening], *, path: Path) -> dict[int, frozenset[Language]]:
    """TMDB original and spoken languages of the screenings' stored movies."""
    ids = {s.tmdb_id for s in screenings if s.tmdb_id is not None}
    return {
        tmdb_id: frozenset().union(
            *(tmdb.languages(code) for code in [m.original_language, *(m.spoken_languages or [])])
        )
        for tmdb_id, m in store.read_movies(ids, path=path).items()
    }


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

    # An empty parse more likely means a changed site than an empty programme.
    if not screenings:
        log.warning("parser=%s found no screenings; keeping stored data", args.parser)
        return

    screenings = mark_dubbed(screenings, films, tmdb_languages(screenings, path=args.output))
    n = store.write_screenings(
        screenings,
        path=args.output,
        source=args.parser,
        venues=venues,
        replaces_sources=getattr(mod, "REPLACES_SOURCES", ()),
    )
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
